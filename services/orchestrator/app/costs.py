"""Gemini token usage and cost per call (baseline for the Layer 5 cost comparison).

Keep in sync with services/system-one/app/costs.py.

Prices in USD per 1M tokens. Thinking ("thoughts") tokens are billed as output.
Source: https://cloud.google.com/vertex-ai/generative-ai/pricing (checked 2026-10-17).
"""

from dataclasses import asdict, dataclass

# model -> (input, output) USD per 1M tokens
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # Introductory rate through 2026-12-31; standard rate from 2027-01-01 is 1.50 / 7.50.
    "gemini-3.8-flash": (0.75, 3.75),
    # TODO(pricing): add gemini-3.5-flash-lite once confirmed on the pricing page.
}


@dataclass(frozen=True)
class Usage:
    model: str
    prompt_tokens: int
    output_tokens: int
    thoughts_tokens: int
    cost_usd: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def cost_usd(model: str, prompt_tokens: int, output_tokens: int, thoughts_tokens: int) -> float | None:
    """None when the model's price is unknown, so unpriced calls are never counted as free."""
    prices = PRICES_USD_PER_MTOK.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    return (prompt_tokens * input_price + (output_tokens + thoughts_tokens) * output_price) / 1_000_000


def usage_from_response(model: str, response) -> Usage | None:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    prompt = meta.prompt_token_count or 0
    output = meta.candidates_token_count or 0
    thoughts = meta.thoughts_token_count or 0
    return Usage(model, prompt, output, thoughts, cost_usd(model, prompt, output, thoughts))


def log_usage(stage: str, usage: Usage | None, **ids) -> None:
    """One structured log line per Gemini call; Cloud Logging ingests it from stdout."""
    import json
    import sys

    if usage is None:
        return
    entry = {"severity": "INFO", "message": f"gemini usage ({stage})", "event": "gemini_usage",
             "stage": stage, **ids, "usage": usage.as_dict()}
    print(json.dumps(entry), file=sys.stdout, flush=True)
