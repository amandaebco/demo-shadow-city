"""Layer 1 result summary: an analyst report (CONTRACT.md §2.6) written by Gemini from metrics.

Gemini interprets the metrics Track B computed; it may quote those numbers but never
derives new ones. Layer 3 extends this to baseline-vs-variant comparison.
"""

import json

from google.genai import types

from app.compare import MIN_AREA_RESIDENTS, area_view, comparable, compute_deltas, scenario_changes
from app.costs import log_usage, usage_from_response

GENERATED_BY = "gemini-system-two"
STANDARD_CAVEAT = "Synthetic population; directional results only."
NOT_COMPARABLE_CAVEAT = (
    "The baseline uses a different population or seed, so differences mix policy effects with population differences."
)
AREA_INSTRUCTION = (
    "Areas: residents are spread thinly over kelurahan, so describe places at kecamatan level using "
    "the by_kecamatan rows and the kecamatan_* rankings, which are weighted by residents. Name a kelurahan "
    "only if it appears in kelurahan_with_enough_residents. Whenever you name an area, give its number of "
    "residents, e.g. 'Cilincing (31 residents)'."
)


def area_caveat(counts: dict[str, int]) -> str:
    residents = sum(counts.values())
    return (
        f"Area results come from {residents:,} simulated residents; kelurahan with fewer than "
        f"{MIN_AREA_RESIDENTS} residents are only reported within their kecamatan."
    )


NO_BASELINE_CAVEAT = "No baseline scenario was compared, so these results cannot be attributed to the policies or events."

SYSTEM_INSTRUCTION = (
    "You are a transport-policy analyst for Jakarta. You receive one simulated scenario "
    "(its policies and events) and the metrics computed by a deterministic simulation engine. "
    "Write a short, plain-English analyst report for city planners. "
    "Only quote numbers that appear in the metrics; never calculate, estimate or invent numbers. "
    "Write numbers in plain language with units, e.g. '27 minutes', 'Rp 9,320', '4% of trips' "
    "(a fraction may be written as a percentage); never write metric field names such as avg_travel_min. "
    "Name which groups (kelurahan, income bands) fare better or worse and why, based on the metrics. "
    "Headline: one sentence. winners, losers, recommendations, caveats: 1-4 short items each."
)


def report_id_for(scenario_id: str) -> str:
    return f"r_analyst_{scenario_id.removeprefix('s_')}"


def report_schema() -> dict:
    string_list = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "winners": string_list,
            "losers": string_list,
            "recommendations": string_list,
            "caveats": string_list,
        },
        "required": ["headline", "winners", "losers", "recommendations", "caveats"],
    }


def _facts(scenario: dict) -> dict:
    return {
        "scenario_id": scenario.get("scenario_id"),
        "name": scenario.get("name"),
        "seed": scenario.get("seed"),
        "population_size": scenario.get("population_size"),
        "policies": scenario.get("policies", []),
        "events": scenario.get("events", []),
    }


def build_comparison_prompt(
    scenario: dict, metrics: dict, base_scenario: dict, base_metrics: dict, counts: dict[str, int] | None = None
) -> str:
    """Layer 3: the variant against its baseline. Every difference is precomputed by code."""
    problems = comparable(base_scenario, scenario)
    parts = [
        "Policy scenario (variant):\n" + json.dumps(_facts(scenario), ensure_ascii=False),
        "Baseline scenario:\n" + json.dumps(_facts(base_scenario), ensure_ascii=False),
        "What differs between them:\n" + json.dumps(scenario_changes(base_scenario, scenario), ensure_ascii=False),
        "Baseline citywide metrics:\n" + json.dumps(base_metrics.get("citywide", {}), ensure_ascii=False),
        "Variant citywide metrics:\n" + json.dumps(metrics.get("citywide", {}), ensure_ascii=False),
        "Differences, variant minus baseline, computed by code (minutes, IDR, counts; mode share in "
        "percentage points):\n" + json.dumps(compute_deltas(base_metrics, metrics, counts), ensure_ascii=False),
    ]
    if counts is not None:
        parts.append(AREA_INSTRUCTION)
    if problems:
        parts.append(
            "The two runs are NOT a clean counterfactual (" + "; ".join(problems) + "). Describe the differences, "
            "but do not attribute them to the policies or events. A caveat about this is added automatically."
        )
    else:
        parts.append(
            "Both runs use the same synthetic population and random seed, so the differences come from the "
            "policy and event changes listed above. Explain who gains and who loses because of them, quoting "
            "the precomputed differences. Winners: groups whose travel time or cost fell most. Losers: groups "
            "whose travel time, cost or stuck count rose most. Recommendations should follow from these differences."
        )
    return "\n\n".join(parts)


def build_prompt(scenario: dict, metrics: dict, counts: dict[str, int] | None = None) -> str:
    facts = {
        "name": scenario.get("name"),
        "population_size": scenario.get("population_size"),
        "policies": scenario.get("policies", []),
        "events": scenario.get("events", []),
    }
    if counts is not None:
        metrics = {k: v for k, v in metrics.items() if k != "by_kelurahan"} | area_view(metrics, counts)
    prompt = (
        "Scenario:\n" + json.dumps(facts, ensure_ascii=False)
        + "\n\nMetrics from the simulation engine:\n" + json.dumps(metrics, ensure_ascii=False)
    )
    if counts is not None:
        prompt += "\n\n" + AREA_INSTRUCTION
    if not scenario.get("base_scenario_id"):
        prompt += (
            "\n\nThere is no baseline scenario to compare against. Describe the outcomes only. "
            "Do not claim that any policy or event caused, raised, lowered, kept, reduced or prevented "
            "any value, and do not recommend policy changes based on assumed effects. "
            "A caveat about the missing baseline is added automatically; do not repeat it."
        )
    return prompt


def _strings(value, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


class ReportWriter:
    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    async def write(
        self, scenario: dict, metrics: dict, base_scenario: dict | None = None, base_metrics: dict | None = None,
        counts: dict[str, int] | None = None,
    ) -> dict:
        if base_scenario is not None and base_metrics is not None:
            prompt = build_comparison_prompt(scenario, metrics, base_scenario, base_metrics, counts)
        else:
            prompt = build_prompt(scenario, metrics, counts)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=report_schema(),
            ),
        )
        log_usage("report", usage_from_response(self._model, response), scenario_id=scenario["scenario_id"])
        parsed = json.loads(response.text)
        if not isinstance(parsed, dict) or not str(parsed.get("headline") or "").strip():
            raise ValueError("Gemini returned no headline")
        caveats = _strings(parsed.get("caveats"))
        # Fixed caveats are added by code, never left to the model.
        if base_scenario is None:
            if NO_BASELINE_CAVEAT not in caveats:
                caveats.insert(0, NO_BASELINE_CAVEAT)
        elif comparable(base_scenario, scenario) and NOT_COMPARABLE_CAVEAT not in caveats:
            caveats.insert(0, NOT_COMPARABLE_CAVEAT)
        if counts:
            caveats.insert(0, area_caveat(counts))
        if STANDARD_CAVEAT not in caveats:
            caveats.insert(0, STANDARD_CAVEAT)
        return {
            "report_id": report_id_for(scenario["scenario_id"]),
            "scenario_id": scenario["scenario_id"],
            "base_scenario_id": scenario.get("base_scenario_id"),
            "headline": str(parsed["headline"]).strip(),
            "winners": _strings(parsed.get("winners")),
            "losers": _strings(parsed.get("losers")),
            "recommendations": _strings(parsed.get("recommendations")),
            "caveats": caveats,
            "generated_by": GENERATED_BY,
            "model_version": self._model,
        }
