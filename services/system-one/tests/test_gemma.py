import asyncio
import json
from types import SimpleNamespace

import httpx

from app.gemini_decider import GeminiDecider
from app.gemma import OllamaGemma
from app.models import DecidedBy, DecisionRequestItem
from tests.test_cache import MemoryCache, Seeds

GOOD = {"probabilities": {"motorcycle": 0.1, "transjakarta": 0.7, "krl": 0.1, "ojol": 0.1}, "reason_short": "Cheaper."}


class FakeGemma:
    model = "gemma4:e4b"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    async def ask(self, system, prompt, schema):
        self.calls += 1
        if self.fail:
            raise RuntimeError("gpu cold start timed out")
        return GOOD, None


class Gemini:
    def __init__(self):
        self.calls = 0

    async def generate_content(self, model, contents, config):
        self.calls += 1
        return SimpleNamespace(text=json.dumps(GOOD))


def decider(gemma, cache=None):
    gemini = Gemini()
    d = GeminiDecider(SimpleNamespace(aio=SimpleNamespace(models=gemini)), "gemini-x", "", Seeds(),
                      concurrency=2, cache=cache, primary=gemma)
    return d, gemini


def test_gemma_decides_first_and_is_cached(item):
    cache, gemma = MemoryCache(), FakeGemma()
    d, gemini = decider(gemma, cache)
    (outcome,) = asyncio.run(d.decide_batch([DecisionRequestItem.model_validate(item)]))
    assert outcome.response.decided_by is DecidedBy.gemma_system_one
    assert outcome.response.model_version == "gemma4:e4b" and d.model_version == "gemma4:e4b"
    assert gemini.calls == 0 and len(cache.store) == 1


def test_gemini_takes_over_when_gemma_fails_and_is_not_cached(item):
    cache = MemoryCache()
    d, gemini = decider(FakeGemma(fail=True), cache)
    (outcome,) = asyncio.run(d.decide_batch([DecisionRequestItem.model_validate(item)]))
    assert outcome.response.decided_by is DecidedBy.gemini_system_two and gemini.calls == 1
    assert cache.store == {}


def test_ollama_request_shape_and_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD)},
                                         "prompt_eval_count": 420, "eval_count": 55})

    class Tokens:
        async def get(self):
            return "tok"

    g = OllamaGemma("https://gemma.example/", "gemma4:e4b", Tokens(), transport=httpx.MockTransport(handler))
    raw, usage = asyncio.run(g.ask("sys", "prompt", {"type": "object"}))
    assert raw == GOOD and seen["url"] == "https://gemma.example/api/chat" and seen["auth"] == "Bearer tok"
    assert seen["body"]["format"] == {"type": "object"} and seen["body"]["options"]["temperature"] == 0
    assert (usage.prompt_tokens, usage.output_tokens, usage.cost_usd) == (420, 55, None)
