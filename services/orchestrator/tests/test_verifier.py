import asyncio
import json
from types import SimpleNamespace

from app.verifier import (
    Verifier, check_baseline_stuck, check_mode_share, check_population_size, coherence_check,
    coherence_sample, overall,
)


def personas(n):
    return [{"persona_id": f"p_{i:03d}", "age": 20 + i % 40, "income_band": ["low", "high"][i % 2],
             "home": {"kelurahan": "Gambir"}, "usual_mode": "krl", "vehicles": []} for i in range(n)]


def test_mode_share_bands_against_reference():
    near = check_mode_share({"motorcycle": 0.40, "ojol": 0.15, "car": 0.12, "transjakarta": 0.2, "krl": 0.08})
    assert near["status"] == "pass" and "Jakarta Post" in near["detail"]
    far = check_mode_share({"krl": 0.5, "mrt": 0.4, "car": 0.1})
    assert far["status"] == "fail"


def test_mode_share_counts_ojol_as_two_wheeler():
    detail = check_mode_share({"motorcycle": 0.342, "ojol": 0.159, "car": 0.157, "transjakarta": 0.237,
                               "krl": 0.063, "mrt": 0.02})["detail"]
    assert "two wheeler 50.1% vs 58.0% (-7.9 pp)" in detail


def test_population_size_and_stuck():
    assert check_population_size({"population_size": 3}, personas(3))["status"] == "pass"
    assert check_population_size({"population_size": 4}, personas(3))["status"] == "fail"
    assert check_baseline_stuck({}, {"citywide": {"stuck_count": 2}})["status"] == "warn"


def test_overall():
    assert overall([{"status": "pass"}, {"status": "warn"}]) == "warn"
    assert overall([{"status": "pass"}, {"status": "fail"}]) == "fail"
    assert overall([{"status": "pass"}]) == "pass"


def test_coherence_sample_is_deterministic_and_bounded():
    sample = coherence_sample(personas(1000))
    assert len(sample) == 40 and sample == coherence_sample(personas(1000))
    assert sample[0]["persona_id"] == "p_000" and sample[1]["persona_id"] == "p_025"


def test_coherence_thresholds_and_missing_verdicts():
    sample = coherence_sample(personas(10))
    good = [{"persona_id": p["persona_id"], "coherent": True} for p in sample]
    assert coherence_check(sample, good)["status"] == "pass"
    two_bad = [dict(v, coherent=False, issue="car without car") if i < 2 else v for i, v in enumerate(good)]
    result = coherence_check(sample, two_bad)
    assert result["status"] == "warn" and "car without car" in result["detail"]
    assert coherence_check(sample, good[:5])["status"] == "warn"


def test_verify_baseline_includes_reference_checks():
    class Models:
        async def generate_content(self, model, contents, config):
            ids = [json.loads(line)["persona_id"] for line in contents.splitlines()[1:]]
            return SimpleNamespace(text=json.dumps([{"persona_id": i, "coherent": True} for i in ids]))

    v = Verifier(SimpleNamespace(aio=SimpleNamespace(models=Models())), "m")
    scenario = {"scenario_id": "s_base", "population_size": 50, "policies": [], "events": []}
    metrics = {"citywide": {"stuck_count": 0, "mode_share": {"motorcycle": 0.45, "car": 0.13, "krl": 0.27}}}
    report = asyncio.run(v.verify(scenario, metrics, personas(50)))
    names = [c["name"] for c in report["checks"]]
    assert "baseline_mode_share_vs_reference" in names and "persona_profile_coherence" in names
    assert report["report_id"] == "r_verifier_base" and report["overall"] in ("warn", "fail")


def test_verify_variant_skips_baseline_only_checks():
    class Down:
        async def generate_content(self, model, contents, config):
            raise RuntimeError("down")

    v = Verifier(SimpleNamespace(aio=SimpleNamespace(models=Down())), "m")
    scenario = {"scenario_id": "s_var", "population_size": 5, "policies": [{"type": "parking_tariff"}], "events": []}
    report = asyncio.run(v.verify(scenario, {"citywide": {}}, personas(5)))
    names = [c["name"] for c in report["checks"]]
    assert "baseline_mode_share_vs_reference" not in names
    assert report["checks"][-1]["status"] == "warn" and "unavailable" in report["checks"][-1]["detail"]



def test_home_spread_compares_with_official_shares():
    from app.kelurahan import HOME_KELURAHAN, HOME_WEIGHTS
    from app.population import build_skeletons
    from app.verifier import check_home_spread

    weighted = check_home_spread(build_skeletons(3, 4000))
    assert weighted["status"] == "pass" and "Dukcapil" in weighted["detail"]
    one_place = [{"home": {"kelurahan": "Gambir"}}] * 500
    assert check_home_spread(one_place)["status"] == "fail"


def test_age_check_compares_with_official_structure():
    from app.population import build_skeletons
    from app.verifier import check_age

    assert check_age(build_skeletons(3, 4000))["status"] == "pass"
    assert check_age([{"age": 64}] * 200)["status"] == "fail"
