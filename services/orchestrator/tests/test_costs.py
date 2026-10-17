from types import SimpleNamespace

import pytest

from app.costs import cost_usd, usage_from_response


def test_cost_counts_thoughts_as_output():
    # 1M input at 0.75 + (0.5M output + 0.5M thoughts) at 3.75
    assert cost_usd("gemini-3.8-flash", 1_000_000, 500_000, 500_000) == pytest.approx(4.5)


def test_unknown_model_has_no_cost():
    assert cost_usd("gemini-3.5-flash-lite", 100, 10, 0) is None


def test_usage_from_response_handles_missing_counts():
    meta = SimpleNamespace(prompt_token_count=200, candidates_token_count=None, thoughts_token_count=40)
    usage = usage_from_response("gemini-3.8-flash", SimpleNamespace(usage_metadata=meta))
    assert (usage.prompt_tokens, usage.output_tokens, usage.thoughts_tokens) == (200, 0, 40)
    assert usage.cost_usd == pytest.approx((200 * 0.75 + 40 * 3.75) / 1e6)


def test_no_usage_metadata():
    assert usage_from_response("m", SimpleNamespace()) is None


def test_log_usage_writes_one_json_line(capsys):
    import json

    from app.costs import Usage, log_usage

    log_usage("population", Usage("gemini-3.8-flash", 10, 5, 0, 0.0), population_id="pop_s1_n10")
    log_usage("population", None, population_id="pop_s1_n10")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "gemini_usage" and entry["population_id"] == "pop_s1_n10"
