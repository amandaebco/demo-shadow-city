import asyncio
import copy
import json
from types import SimpleNamespace

from app.cache import cache_key
from app.gemini_decider import GeminiDecider
from app.models import DecidedBy, DecisionRequestItem


class MemoryCache:
    def __init__(self, fail_reads=False):
        self.store, self.fail_reads, self.puts = {}, fail_reads, 0

    async def get_many(self, keys):
        if self.fail_reads:
            raise RuntimeError("firestore down")
        return {k: self.store[k] for k in keys if k in self.store}

    async def put_many(self, entries):
        self.puts += 1
        self.store.update(entries)


class CountingModels:
    """Each call returns a different favourite, so replays only match through the cache."""

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    async def generate_content(self, model, contents, config):
        self.calls += 1
        if self.fail:
            raise RuntimeError("down")
        favourite = ["transjakarta", "krl", "ojol", "motorcycle"][self.calls % 4]
        probs = {o: (0.7 if o == favourite else 0.1) for o in ["motorcycle", "transjakarta", "krl", "ojol"]}
        return SimpleNamespace(text=json.dumps({"probabilities": probs, "reason_short": f"call {self.calls}"}))


class Seeds:
    async def get(self, scenario_id):
        return 42


def decider(cache, models):
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiDecider(client, "gemini-x", "", Seeds(), concurrency=4, cache=cache)


def run(coro):
    return asyncio.run(coro)


def make(item, **changes):
    data = copy.deepcopy(item)
    data.update(changes)
    return DecisionRequestItem.model_validate(data)


def test_key_ignores_request_id_and_scenario_but_not_context(item):
    a = make(item, request_id="q_1")
    b = make(item, request_id="q_2", scenario_id="s_other")
    assert cache_key(a, 42, "m") == cache_key(b, 42, "m")
    changed = copy.deepcopy(item)
    changed["context"]["options_detail"]["krl"]["est_minutes"] = 66
    assert cache_key(a, 42, "m") != cache_key(make(changed), 42, "m")
    assert cache_key(a, 42, "m") != cache_key(a, 43, "m")
    assert cache_key(a, 42, "m") != cache_key(make(item, tick=85), 42, "m")
    assert cache_key(a, 42, "m") != cache_key(a, 42, "other-model")


def test_second_run_replays_identically_without_model_calls(item):
    cache, models = MemoryCache(), CountingModels()
    first = run(decider(cache, models).decide_batch([make(item, request_id="run1")]))
    calls_after_first = models.calls
    second = run(decider(cache, CountingModels()).decide_batch([make(item, request_id="run2")]))
    assert first[0].cache == "miss" and second[0].cache == "hit"
    assert second[0].usage is None
    keep = ("probabilities", "chosen", "reason_short", "decided_by", "model_version")
    assert first[0].response.model_dump(include=set(keep)) == second[0].response.model_dump(include=set(keep))
    assert second[0].response.request_id == "run2"
    assert calls_after_first == 1


def test_identical_requests_in_one_batch_are_decided_once(item):
    cache, models = MemoryCache(), CountingModels()
    outcomes = run(decider(cache, models).decide_batch([make(item, request_id=f"q_{i}") for i in range(3)]))
    assert models.calls == 1
    assert [o.cache for o in outcomes] == ["miss", "hit", "hit"]
    assert len({o.response.chosen for o in outcomes}) == 1
    assert [o.response.request_id for o in outcomes] == ["q_0", "q_1", "q_2"]


def test_rule_fallback_is_not_cached(item):
    cache = MemoryCache()
    outcome = run(decider(cache, CountingModels(fail=True)).decide_batch([make(item)]))[0]
    assert outcome.response.decided_by is DecidedBy.rule_fallback
    assert cache.store == {}


def test_cache_read_failure_falls_back_to_model(item):
    models = CountingModels()
    outcome = run(decider(MemoryCache(fail_reads=True), models).decide_batch([make(item)]))[0]
    assert outcome.cache == "miss" and models.calls == 1
