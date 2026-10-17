import asyncio
import json
from types import SimpleNamespace

from app.gemini_decider import GeminiDecider, build_prompt, response_schema
from app.models import DecidedBy, DecisionRequestItem, Mode
from app.sampling import decision_rng, normalize_probabilities, sample


class FakeModels:
    def __init__(self, replies: dict):
        self.replies = replies  # model name -> JSON text, or an Exception to raise
        self.calls = []

    async def generate_content(self, model, contents, config):
        self.calls.append(model)
        reply = self.replies[model]
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)


class FakeSeeds:
    async def get(self, scenario_id):
        return 42


def make_decider(replies: dict) -> tuple[GeminiDecider, FakeModels]:
    models = FakeModels(replies)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiDecider(client, "primary", "fallback", FakeSeeds(), concurrency=4), models


GOOD = json.dumps({
    "probabilities": {"motorcycle": 0.2, "transjakarta": 0.6, "krl": 0.1, "ojol": 0.1},
    "reason_short": "Usual route is flooded; transit is cheaper.",
})


def run(coro):
    return asyncio.run(coro)


def test_gemini_decision_fields(item):
    decider, _ = make_decider({"primary": GOOD})
    req = DecisionRequestItem.model_validate(item)
    result = run(decider.decide(req))
    assert result.decided_by is DecidedBy.gemini_system_two
    assert result.model_version == "primary"
    assert result.reason_short == "Usual route is flooded; transit is cheaper."
    assert sum(result.probabilities.values()) == 1.0
    expected = sample(
        normalize_probabilities(json.loads(GOOD)["probabilities"], req.options),
        decision_rng(42, req.tick, req.persona_id),
    )
    assert result.chosen is expected


def test_falls_back_to_second_model(item):
    decider, models = make_decider({"primary": RuntimeError("quota"), "fallback": GOOD})
    result = run(decider.decide(DecisionRequestItem.model_validate(item)))
    assert models.calls == ["primary", "fallback"]
    assert result.model_version == "fallback"
    assert result.decided_by is DecidedBy.gemini_system_two


def test_falls_back_to_rule_when_all_models_fail(item):
    decider, _ = make_decider({"primary": RuntimeError("down"), "fallback": "not json"})
    result = run(decider.decide(DecisionRequestItem.model_validate(item)))
    assert result.decided_by is DecidedBy.rule_fallback
    assert result.chosen is Mode.transjakarta


def test_long_reason_is_truncated(item):
    reply = json.dumps({"probabilities": {"krl": 1}, "reason_short": "x" * 500})
    decider, _ = make_decider({"primary": reply})
    result = run(decider.decide(DecisionRequestItem.model_validate(item)))
    assert len(result.reason_short) == 140
    assert result.reason_short.endswith("…")
    assert result.chosen is Mode.krl


def test_batch_keeps_order(item):
    decider, _ = make_decider({"primary": GOOD})
    items = []
    for i in range(10):
        it = dict(item, request_id=f"q_{i}")
        items.append(DecisionRequestItem.model_validate(it))
    results = run(decider.decide_batch(items))
    assert [r.request_id for r in results] == [f"q_{i}" for i in range(10)]


def test_prompt_and_schema_cover_only_listed_options(item):
    item["options"] = ["transjakarta", "krl"]
    req = DecisionRequestItem.model_validate(item)
    prompt = build_prompt(req)
    assert "transjakarta: 58 min, 3500 IDR, flooded on route: no" in prompt
    assert "motorcycle" not in prompt.split("Options")[1]
    schema = response_schema(req)
    assert schema["properties"]["probabilities"]["required"] == ["transjakarta", "krl"]


def test_reason_flags_sampled_minority_option():
    from app.gemini_decider import explain

    probs = {Mode.transjakarta: 0.65, Mode.ojol: 0.05, Mode.krl: 0.3}
    reason = explain(Mode.ojol, probs, "Transit is cheaper.")
    assert reason.startswith("Sampled ojol (p=0.05); model favored transjakarta (p=0.65).")
    assert explain(Mode.transjakarta, probs, "Transit is cheaper.") == "Transit is cheaper."


def test_truncate_reason_cuts_at_word_boundary():
    from app.models import truncate_reason

    text = "Sampled ojol (p=0.05); model favored transjakarta (p=0.55). " + "Transjakarta is the fastest option " * 5
    out = truncate_reason(text)
    assert len(out) <= 140
    assert out.endswith("…")
    assert out[:-1] == text[: len(out) - 1]
    assert text[len(out) - 1] in " ,.;:"
    assert truncate_reason("short") == "short"
