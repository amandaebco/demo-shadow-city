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
from app.costs import Usage, usage_from_response
from app.models import (
    DecidedBy,
    DecisionRequestItem,
    DecisionResponseItem,
    Mode,
    truncate_reason,
)
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


class GeminiDecider:
    def __init__(self, client, model: str, fallback_model: str, seeds, concurrency: int, personas=None):
        self._client = client
        self._models = [m for m in (model, fallback_model) if m]
        self._seeds = seeds
        self._personas = personas
        self._semaphore = asyncio.Semaphore(concurrency)

    async def decide_batch(
        self, items: list[DecisionRequestItem]
    ) -> list[tuple[DecisionResponseItem, Usage | None]]:
        return list(await asyncio.gather(*(self.decide_with_usage(item) for item in items)))

    async def decide(self, item: DecisionRequestItem) -> DecisionResponseItem:
        return (await self.decide_with_usage(item))[0]

    async def decide_with_usage(self, item: DecisionRequestItem) -> tuple[DecisionResponseItem, Usage | None]:
        started = time.perf_counter()
        persona = await self._personas.get(item.persona_id) if self._personas else None
        async with self._semaphore:
            for model in self._models:
                try:
                    raw, usage = await self._ask(model, item, persona)
                    break
                except Exception:
                    logger.exception("Gemini model %s failed for %s", model, item.request_id)
            else:
                # Every Gemini model failed: last-resort rule decision (decided_by: rule-fallback).
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
            decided_by=DecidedBy.gemini_system_two,
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
            ),
        )
        parsed = json.loads(response.text)
        if not isinstance(parsed, dict):
            raise ValueError("Gemini returned non-object JSON")
        return parsed, usage_from_response(model, response)
