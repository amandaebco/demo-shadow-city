#!/usr/bin/env python3
"""Does lowering Gemini's thinking level change System One decisions, and what does it save?

Samples fresh Gemini decisions from BigQuery `shadow_city.decisions`, rebuilds the exact System One
prompt, and asks the same model again under each thinking level. The `default` arm re-asks with
the production configuration, so its agreement with the logged decision is the model's own
run-to-run variation: the yardstick for the other arms.

Usage (from the repo root):
  PYTHONPATH=services/system-one services/system-one/.venv/bin/python ml/distillation/eval_thinking.py --n 100
"""

import argparse
import asyncio
import json
import statistics
from datetime import date
from pathlib import Path

from google import genai
from google.cloud import firestore
from google.genai import types

from app.costs import usage_from_response
from app.gemini_decider import SYSTEM_INSTRUCTION, build_prompt, response_schema
from app.models import DecisionRequestItem
from app.personas import PersonaLookup
from app.sampling import normalize_probabilities
from eval_agreement import PROJECT, favourite, sample_decisions, top2, tv_distance

RESULTS = Path(__file__).resolve().parent / "results"
# gemini-3.8-flash rejects MINIMAL ("Thinking level is unsupported"), so it is not an arm.
LEVELS = {"default": None, "low": types.ThinkingLevel.LOW}


async def ask(client, model, level, prompt, schema, options):
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION, temperature=0,
        response_mime_type="application/json", response_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=level) if level else None,
    )
    response = await client.aio.models.generate_content(model=model, contents=prompt, config=config)
    raw = json.loads(response.text)
    probs = {o.value: p for o, p in normalize_probabilities(raw.get("probabilities") or {}, options).items()}
    return probs, usage_from_response(model, response)


async def run_arm(client, model, name, level, samples, prompts, concurrency):
    semaphore = asyncio.Semaphore(concurrency)
    rows = []

    async def one(sample, prompt, schema, options):
        async with semaphore:
            try:
                probs, usage = await ask(client, model, level, prompt, schema, options)
                rows.append({"gemma": probs, "logged": sample["gemini"], "usage": usage})
            except Exception as exc:
                print(f"  {name}: {type(exc).__name__}: {str(exc)[:120]}")

    await asyncio.gather(*(one(s, *p) for s, p in zip(samples, prompts)))
    if not rows:
        return {"arm": name, "n": 0, "error": "every call failed"}
    usages = [r["usage"] for r in rows if r["usage"]]
    return {
        "arm": name,
        "n": len(rows),
        "top1_agreement_with_logged": round(sum(favourite(r["gemma"]) == favourite(r["logged"]) for r in rows) / len(rows), 3),
        "top2_contains_logged_favourite": round(sum(favourite(r["logged"]) in top2(r["gemma"]) for r in rows) / len(rows), 3),
        "mean_tv_distance": round(statistics.mean(tv_distance(r["gemma"], r["logged"]) for r in rows), 3),
        "mean_thoughts_tokens": round(statistics.mean(u.thoughts_tokens for u in usages), 1),
        "mean_cost_usd_per_decision": round(statistics.mean(u.cost_usd for u in usages if u.cost_usd is not None), 6),
    }


async def main_async(args):
    samples = sample_decisions(args.n)
    print(f"{len(samples)} Gemini decisions sampled from BigQuery")
    personas = PersonaLookup(firestore.Client(project=PROJECT, database="shadow-city"))
    prompts = []
    for s in samples:
        item = DecisionRequestItem.model_validate(s["request"])
        prompts.append((build_prompt(item, await personas.get(item.persona_id)), response_schema(item), item.options))
    client = genai.Client(vertexai=True, project=PROJECT, location="global")
    results = []
    for name, level in LEVELS.items():
        results.append(await run_arm(client, args.model, name, level, samples, prompts, args.concurrency))
        print(json.dumps(results[-1]))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"thinking_levels_{date.today().isoformat()}.json"
    out.write_text(json.dumps({"model": args.model, "samples": len(samples), "results": results}, indent=1) + "\n")
    print(f"saved {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--concurrency", type=int, default=16)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
