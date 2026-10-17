import asyncio

import pytest

from app.models import Mode
from app.population import PersonaGenerator, build_skeletons, merge_profile, persona_id_for, population_id_for
from tests.conftest import FakeGeminiModels, fake_client, fake_profile


def test_ids():
    assert population_id_for(42, 50) == "pop_s42_n50"
    assert persona_id_for("pop_s42_n50", 7) == "p_s42_n50_00007"


def test_skeletons_are_deterministic():
    assert build_skeletons(42, 50) == build_skeletons(42, 50)
    assert build_skeletons(42, 50) != build_skeletons(43, 50)


def test_skeleton_fields():
    skeletons = build_skeletons(1, 30)
    assert len({s["persona_id"] for s in skeletons}) == 30
    for s in skeletons:
        assert 18 <= s["age"] <= 64
        assert s["population_id"] == "pop_s1_n30"
        assert -6.4 < s["home"]["lat"] < -6.0 and 106.6 < s["home"]["lng"] < 107.0


def test_merge_repairs_values():
    skeleton = build_skeletons(1, 1)[0]
    profile = fake_profile(0) | {
        "vehicles": ["motorcycle", "motorcycle", "bicycle"],
        "usual_mode": "car",
        "usual_departure_tick": 999,
        "cost_sensitivity": 1.7,
        "time_sensitivity": "fast",
    }
    persona = merge_profile(skeleton, profile)
    assert persona.vehicles == [Mode.motorcycle, Mode.car]
    assert persona.usual_departure_tick == 203
    assert persona.cost_sensitivity == 1.0
    assert persona.time_sensitivity == 0.5
    assert persona.memory == []


def test_generate_batches_and_keeps_order():
    models = FakeGeminiModels()
    personas = asyncio.run(PersonaGenerator(fake_client(models), "m").generate(build_skeletons(42, 60)))
    assert models.calls == 3  # 25 + 25 + 10
    assert [p.persona_id for p in personas] == [persona_id_for("pop_s42_n60", i) for i in range(60)]


def test_generate_fails_after_retries():
    models = FakeGeminiModels(fail=True)
    with pytest.raises(RuntimeError):
        asyncio.run(PersonaGenerator(fake_client(models), "m").generate(build_skeletons(42, 10)))
    assert models.calls == 2


def test_kelurahan_data_covers_mainland_jakarta():
    from app.kelurahan import HOME_KELURAHAN, WORK_KELURAHAN

    assert len(HOME_KELURAHAN) == 262
    assert len({k[1] for k in HOME_KELURAHAN}) == 42
    assert not any(k[1].startswith("Kepulauan Seribu") for k in HOME_KELURAHAN)
    for _, _, lat, lng in HOME_KELURAHAN:
        assert -6.40 < lat < -6.05 and 106.65 < lng < 107.0
    assert len(WORK_KELURAHAN) == 8


def test_skeleton_homes_spread_across_jakarta():
    homes = {s["home"]["kelurahan"] for s in build_skeletons(42, 1000)}
    assert len(homes) > 200
