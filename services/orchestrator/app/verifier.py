"""Verifier agent (Layer 4, REFERENCE.md §6.8; report shape CONTRACT.md §2.6).

Checks whether a scenario's population and baseline results are plausible. Every status is
decided by code against stated thresholds; where no official reference is integrated yet,
the check says so with a warn instead of comparing against invented numbers. Gemini, in its
own context (it never sees the prompts that created the personas), judges a sample of
persona profiles for internal coherence.
"""

import json
import statistics
from collections import Counter

from google.genai import types

from app.compare import KECAMATAN_OF
from app.costs import log_usage, usage_from_response

COHERENCE_SAMPLE = 40

# BPS Jakarta commuter survey, 2014 data, as reported by The Jakarta Post on 17 Feb 2015.
MODE_SHARE_REFERENCE = {
    "source": "BPS Jakarta commuter survey (2014 data), reported by The Jakarta Post, 17 Feb 2015",
    "url": "https://www.thejakartapost.com/news/2015/02/17/138-million-commute-jakarta-daily",
    "two_wheeler": 0.58,
    "car": 0.128,
    "public_transport": 0.27,
}
PASS_PP, WARN_PP = 10.0, 20.0

COHERENCE_INSTRUCTION = (
    "You audit synthetic residents of Jakarta for a transport simulator. For each resident, decide "
    "whether the profile is internally coherent: occupation, income band, age, vehicles owned, usual "
    "commute mode, and cost/time sensitivity should be plausible together (for example, a usual mode of "
    "car requires owning a car; a low income band with very low cost sensitivity is suspicious). "
    "Judge only coherence, not realism of the city. Return every resident with coherent true or false "
    "and, when false, a short issue."
)


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def overall(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    return "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"


def check_population_size(scenario: dict, personas: list[dict]) -> dict:
    expected = scenario.get("population_size")
    status = "pass" if len(personas) == expected else "fail"
    return _check("population_size_matches", status, f"{len(personas)} personas stored for population_size {expected}.")


def check_home_spread(personas: list[dict]) -> dict:
    homes = Counter((p.get("home") or {}).get("kelurahan") for p in personas)
    kecamatan = {KECAMATAN_OF[k] for k in homes if k in KECAMATAN_OF}
    return _check(
        "home_distribution_vs_reference", "warn",
        f"Homes cover {len(homes)} kelurahan in {len(kecamatan)} of 42 mainland kecamatan, drawn uniformly per "
        "kelurahan. No official population per kelurahan is integrated yet (TODO: Dukcapil/BPS), so density "
        "is not compared against a reference.",
    )


def check_age(personas: list[dict]) -> dict:
    ages = [p["age"] for p in personas if isinstance(p.get("age"), int)]
    if not ages:
        return _check("age_distribution_vs_reference", "fail", "No ages found.")
    return _check(
        "age_distribution_vs_reference", "warn",
        f"Ages {min(ages)}–{max(ages)}, median {statistics.median(ages):g}, drawn uniformly over working age. "
        "No official age distribution is integrated yet (TODO: BPS), so it is not compared against a reference.",
    )


def check_income(personas: list[dict]) -> dict:
    counts = Counter(p.get("income_band") for p in personas)
    total = sum(counts.values()) or 1
    shares = ", ".join(f"{band} {counts[band] / total:.0%}" for band in sorted(counts))
    return _check(
        "income_distribution_vs_reference", "warn",
        f"Income bands: {shares}. Drawn uniformly; no official income distribution is integrated yet "
        "(TODO: BPS), so it is not compared against a reference.",
    )


def check_mode_share(citywide_share: dict) -> dict:
    """Baseline mode share against the cited reference, with ±10 pp pass and ±20 pp warn bands."""
    ours = {
        # Ojol (motorcycle taxi) counts as two-wheeler: the reference predates ride-hailing's spread.
        "two_wheeler": citywide_share.get("motorcycle", 0) + citywide_share.get("ojol", 0),
        "car": citywide_share.get("car", 0),
        "public_transport": sum(citywide_share.get(m, 0) for m in ("transjakarta", "krl", "mrt")),
    }
    ref = MODE_SHARE_REFERENCE
    gaps = {k: (ours[k] - ref[k]) * 100 for k in ours}
    worst = max(abs(g) for g in gaps.values())
    status = "pass" if worst <= PASS_PP else "warn" if worst <= WARN_PP else "fail"
    parts = [f"{k.replace('_', ' ')} {ours[k]:.1%} vs {ref[k]:.1%} ({gaps[k]:+.1f} pp)" for k in ours]
    return _check(
        "baseline_mode_share_vs_reference", status,
        "; ".join(parts) + f". Motorcycle alone is {citywide_share.get('motorcycle', 0):.1%}, ojol "
        f"{citywide_share.get('ojol', 0):.1%}. Reference: {ref['source']} ({ref['url']}); it covers commuters "
        f"entering Jakarta in 2014, so it is a plausibility band (pass within {PASS_PP:g} pp, warn within "
        f"{WARN_PP:g} pp), not a target.",
    )


def check_baseline_stuck(scenario: dict, metrics: dict) -> dict:
    stuck = (metrics.get("citywide") or {}).get("stuck_count", 0)
    status = "pass" if stuck == 0 else "warn"
    return _check("baseline_without_events_has_no_stuck_residents", status,
                  f"{stuck} residents stuck in a scenario with no events.")


def coherence_sample(personas: list[dict]) -> list[dict]:
    """Evenly spaced, deterministic sample across the population."""
    step = max(1, len(personas) // COHERENCE_SAMPLE)
    fields = ("persona_id", "age", "occupation", "income_band", "vehicles", "usual_mode",
              "cost_sensitivity", "time_sensitivity", "profile_summary")
    return [{f: p.get(f) for f in fields} for p in personas[::step][:COHERENCE_SAMPLE]]


def coherence_schema() -> dict:
    return {"type": "array", "items": {"type": "object", "properties": {
        "persona_id": {"type": "string"}, "coherent": {"type": "boolean"}, "issue": {"type": "string"}},
        "required": ["persona_id", "coherent"]}}


def coherence_check(sample: list[dict], verdicts: list[dict]) -> dict:
    ids = {p["persona_id"] for p in sample}
    judged = {v["persona_id"]: v for v in verdicts if v.get("persona_id") in ids}
    if len(judged) < len(ids):
        return _check("persona_profile_coherence", "warn",
                      f"The verifier judged only {len(judged)} of {len(ids)} sampled personas.")
    bad = [v for v in judged.values() if not v.get("coherent")]
    share = 1 - len(bad) / len(ids)
    status = "pass" if share >= 0.9 else "warn" if share >= 0.75 else "fail"
    examples = "; ".join(f"{v['persona_id']}: {v.get('issue', '').strip()[:120]}" for v in bad[:3])
    return _check("persona_profile_coherence", status,
                  f"{len(ids) - len(bad)} of {len(ids)} sampled personas coherent ({share:.0%}), judged by Gemini "
                  f"in a separate context." + (f" Issues: {examples}" if examples else ""))


class Verifier:
    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    async def judge_coherence(self, sample: list[dict], scenario_id: str) -> list[dict]:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents="Residents:\n" + "\n".join(json.dumps(p, ensure_ascii=False) for p in sample),
            config=types.GenerateContentConfig(
                system_instruction=COHERENCE_INSTRUCTION, temperature=0,
                response_mime_type="application/json", response_schema=coherence_schema(),
            ),
        )
        log_usage("verifier", usage_from_response(self._model, response), scenario_id=scenario_id)
        parsed = json.loads(response.text)
        return parsed if isinstance(parsed, list) else []

    async def verify(self, scenario: dict, metrics: dict, personas: list[dict]) -> dict:
        checks = [check_population_size(scenario, personas), check_home_spread(personas),
                  check_age(personas), check_income(personas)]
        if not scenario.get("policies") and not scenario.get("events"):
            checks.append(check_mode_share((metrics.get("citywide") or {}).get("mode_share") or {}))
            checks.append(check_baseline_stuck(scenario, metrics))
        sample = coherence_sample(personas)
        try:
            verdicts = await self.judge_coherence(sample, scenario["scenario_id"])
            checks.append(coherence_check(sample, verdicts))
        except Exception as exc:
            checks.append(_check("persona_profile_coherence", "warn", f"Verifier model unavailable: {exc}"[:200]))
        return {
            "report_id": f"r_verifier_{scenario['scenario_id'].removeprefix('s_')}",
            "scenario_id": scenario["scenario_id"],
            "checks": checks,
            "overall": overall(checks),
        }
