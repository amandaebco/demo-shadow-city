"""Gemini-backed decisions for Layer 1–4 (decided_by: gemini-system-two).

Gemini only estimates option probabilities and a short reason. All numbers it sees
(minutes, cost, flooding) come from the simulation engine; it never computes them.
The chosen option is then sampled deterministically from those probabilities.
"""

import asyncio
import json
import logging
import time

from google.genai import types

from app import rules
from app.cache import cache_key
from app.costs import Usage, usage_from_response
from app.models import (
    DecidedBy,
    DecisionRequestItem,
    DecisionResponseItem,
    Mode,
    truncate_reason,
)
from app.outcome import Outcome
from app.sampling import decision_rng, normalize_probabilities, sample

logger = logging.getLogger("system-one")

SYSTEM_INSTRUCTION = (
    "You simulate how one Jakarta resident chooses a travel mode today. "
    "Use only the facts given: the resident's profile, sensitivities, memory, and the "
    "per-option travel time, cost and flooding computed by the simulation engine. "
    "Do not recompute or invent any numbers. "
    "Commuters have habits: their usual mode starts with an advantage, but they switch when "
    "another option is clearly better for them today given their cost and time sensitivity, "
    "or when a policy or event makes their usual option worse. Weigh habit against the "
    "numbers instead of simply repeating the usual mode. "
    "Return a probability for every option (they should sum to 1) reflecting how likely "
    "this resident is to choose it, and a reason of at most 140 characters in English."
)


def habit_lines(item: DecisionRequestItem, persona: dict | None) -> list[str]:
    if not persona:
        return []
    lines = []
    usual = persona.get("usual_mode")
    if usual:
        offered = usual in {o.value for o in item.options}
        lines.append(f"Usual commute mode: {usual}" + ("" if offered else " (not available today)"))
    vehicles = persona.get("vehicles")
    if vehicles is not None:
        lines.append(f"Owns: {', '.join(vehicles) if vehicles else 'no private vehicle'}")
    if persona.get("income_band"):
        lines.append(f"Income band: {persona['income_band']}")
    return lines


def build_prompt(item: DecisionRequestItem, persona: dict | None = None) -> str:
    ctx = item.context
    lines = [
        f"Resident: {ctx.persona_summary}",
        *habit_lines(item, persona),
        f"Cost sensitivity (0-1): {ctx.cost_sensitivity}",
        f"Time sensitivity (0-1): {ctx.time_sensitivity}",
        f"Recent memory: {'; '.join(ctx.memory) if ctx.memory else 'none'}",
        f"Active policies: {', '.join(ctx.active_policies) if ctx.active_policies else 'none'}",
        f"Active events: {', '.join(ctx.active_events) if ctx.active_events else 'none'}",
        f"Simulation tick: {item.tick} (tick 0 = 05:00, 5 minutes per tick)",
        "Options (computed by the simulation engine):",
    ]
    for option in item.options:
        d = ctx.options_detail[option]
        flooded = "yes" if d.flooded_on_route else "no"
        lines.append(f"- {option.value}: {d.est_minutes:g} min, {d.cost_idr} IDR, flooded on route: {flooded}")
    return "\n".join(lines)


def response_schema(item: DecisionRequestItem) -> dict:
    option_names = [o.value for o in item.options]
    return {
        "type": "object",
        "properties": {
            "probabilities": {
                "type": "object",
                "properties": {name: {"type": "number"} for name in option_names},
                "required": option_names,
            },
            "reason_short": {"type": "string"},
        },
        "required": ["probabilities", "reason_short"],
    }


def explain(chosen: Mode, probabilities: dict[Mode, float], model_reason: str) -> str:
    """Gemini's reason explains its preferred option. When sampling picks a less likely
    option, say so, so the evidence chain never shows a reason for a different choice."""
    top = max(probabilities, key=lambda option: probabilities[option])
    if chosen == top or probabilities[chosen] == probabilities[top]:
        return model_reason or f"Chose {chosen.value}."
    return (
        f"Sampled {chosen.value} (p={probabilities[chosen]:.2f}); model favored "
        f"{top.value} (p={probabilities[top]:.2f}). {model_reason}"
    ).strip()


def stored_decision(response: DecisionResponseItem) -> dict:
    """The parts of a decision that do not depend on request_id."""
    return {
        "probabilities": {option.value: p for option, p in response.probabilities.items()},
        "chosen": response.chosen.value,
        "reason_short": response.reason_short,
        "decided_by": response.decided_by.value,
        "model_version": response.model_version,
    }


def from_stored(item: DecisionRequestItem, stored: dict, latency_ms: int) -> DecisionResponseItem:
    return DecisionResponseItem(
        request_id=item.request_id,
        decision_id=rules.decision_id_for(item.request_id),
        probabilities=stored["probabilities"],
        chosen=stored["chosen"],
        reason_short=stored["reason_short"],
        decided_by=stored["decided_by"],
        model_version=stored["model_version"],
        latency_ms=latency_ms,
    )


class GeminiDecider:
    def __init__(self, client, model: str, fallback_model: str, seeds, concurrency: int, personas=None, cache=None,
                 primary=None, thinking_level: str = ""):
        self._client = client
        self._thinking_level = thinking_level
        self._cache = cache
        self._models = [m for m in (model, fallback_model) if m]
        # Layer 5: an optional Gemma backend tried before Gemini (decided_by: gemma-system-one).
        self._primary = primary
        self._primary_decided_by = DecidedBy.gemma_system_one if primary else DecidedBy.gemini_system_two
        self.model_version = primary.model if primary else (self._models[0] if self._models else "")
        # Part of the cache key: decisions made under another thinking level are never replayed.
        self._cache_model = self.model_version + (f"@thinking-{thinking_level}" if thinking_level and not primary else "")
        self._seeds = seeds
        self._personas = personas
        self._semaphore = asyncio.Semaphore(concurrency)

    async def decide_batch(self, items: list[DecisionRequestItem]) -> list[Outcome]:
        if self._cache is None:
            fresh = await asyncio.gather(*(self.decide_with_usage(item) for item in items))
            return [Outcome(response, usage, "off") for response, usage in fresh]

        started = time.perf_counter()
        seeds = [await self._seeds.get(item.scenario_id) for item in items]
        keys = [cache_key(item, seed, self._cache_model) for item, seed in zip(items, seeds)]
        try:
            cached = await self._cache.get_many(keys)
        except Exception:
            logger.exception("Decision cache read failed; deciding without it")
            cached = {}
        lookup_ms = int((time.perf_counter() - started) * 1000)

        # Decide each distinct missing key once, so identical requests in one batch agree.
        first_index: dict[str, int] = {}
        for index, key in enumerate(keys):
            if key not in cached and key not in first_index:
                first_index[key] = index
        fresh = await asyncio.gather(*(self.decide_with_usage(items[i]) for i in first_index.values()))
        fresh_by_key = dict(zip(first_index, fresh))

        to_store = {
            key: stored_decision(response)
            for key, (response, _) in fresh_by_key.items()
            if response.decided_by is self._primary_decided_by  # never cache fallbacks
        }
        try:
            await self._cache.put_many(to_store)
        except Exception:
            logger.exception("Decision cache write failed")

        outcomes = []
        for index, (item, key) in enumerate(zip(items, keys)):
            if key in cached:
                outcomes.append(Outcome(from_stored(item, cached[key], lookup_ms), None, "hit"))
            elif first_index[key] == index:
                response, usage = fresh_by_key[key]
                outcomes.append(Outcome(response, usage, "miss"))
            else:
                stored = stored_decision(fresh_by_key[key][0])
                outcomes.append(Outcome(from_stored(item, stored, lookup_ms), None, "hit"))
        return outcomes

    async def decide(self, item: DecisionRequestItem) -> DecisionResponseItem:
        return (await self.decide_with_usage(item))[0]

    async def decide_with_usage(self, item: DecisionRequestItem) -> tuple[DecisionResponseItem, Usage | None]:
        started = time.perf_counter()
        persona = await self._personas.get(item.persona_id) if self._personas else None
        attempts = ([(self._primary.model, DecidedBy.gemma_system_one)] if self._primary else []) + [
            (m, DecidedBy.gemini_system_two) for m in self._models]
        async with self._semaphore:
            for model, decided_by in attempts:
                try:
                    if decided_by is DecidedBy.gemma_system_one:
                        raw, usage = await self._primary.ask(SYSTEM_INSTRUCTION, build_prompt(item, persona),
                                                             response_schema(item))
                    else:
                        raw, usage = await self._ask(model, item, persona)
                    break
                except Exception:
                    logger.exception("Model %s failed for %s", model, item.request_id)
            else:
                # Every model failed: last-resort rule decision (decided_by: rule-fallback).
                return rules.decide(item), None

        probabilities = normalize_probabilities(raw.get("probabilities") or {}, item.options)
        seed = await self._seeds.get(item.scenario_id)
        chosen = sample(probabilities, decision_rng(seed, item.tick, item.persona_id))
        reason = explain(chosen, probabilities, str(raw.get("reason_short") or "").strip())
        response = DecisionResponseItem(
            request_id=item.request_id,
            decision_id=rules.decision_id_for(item.request_id),
            probabilities=probabilities,
            chosen=chosen,
            reason_short=truncate_reason(reason),
            decided_by=decided_by,
            model_version=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return response, usage

    async def _ask(self, model: str, item: DecisionRequestItem, persona: dict | None) -> tuple[dict, Usage | None]:
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=build_prompt(item, persona),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0,
                response_mime_type="application/json",
                response_schema=response_schema(item),
                thinking_config=(types.ThinkingConfig(thinking_level=self._thinking_level.upper())
                                 if self._thinking_level else None),
            ),
        )
        parsed = json.loads(response.text)
        if not isinstance(parsed, dict):
            raise ValueError("Gemini returned non-object JSON")
        return parsed, usage_from_response(model, response)
