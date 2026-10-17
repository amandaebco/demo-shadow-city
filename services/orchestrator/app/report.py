"""Layer 1 result summary: an analyst report (CONTRACT.md §2.6) written by Gemini from metrics.

Gemini interprets the metrics Track B computed; it may quote those numbers but never
derives new ones. Layer 3 extends this to baseline-vs-variant comparison.
"""

import json

from google.genai import types

from app.costs import log_usage, usage_from_response

GENERATED_BY = "gemini-system-two"
STANDARD_CAVEAT = "Synthetic population; directional results only."

SYSTEM_INSTRUCTION = (
    "You are a transport-policy analyst for Jakarta. You receive one simulated scenario "
    "(its policies and events) and the metrics computed by a deterministic simulation engine. "
    "Write a short, plain-English analyst report for city planners. "
    "Only quote numbers that appear in the metrics; never calculate, estimate or invent numbers. "
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


def build_prompt(scenario: dict, metrics: dict) -> str:
    facts = {
        "name": scenario.get("name"),
        "population_size": scenario.get("population_size"),
        "policies": scenario.get("policies", []),
        "events": scenario.get("events", []),
    }
    return (
        "Scenario:\n" + json.dumps(facts, ensure_ascii=False)
        + "\n\nMetrics from the simulation engine:\n" + json.dumps(metrics, ensure_ascii=False)
    )


def _strings(value, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


class ReportWriter:
    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    async def write(self, scenario: dict, metrics: dict) -> dict:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=build_prompt(scenario, metrics),
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
