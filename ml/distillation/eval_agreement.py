#!/usr/bin/env python3
"""Gemma vs Gemini agreement on logged decisions (Layer 5, REFERENCE.md §6.3).

Samples Gemini decisions from BigQuery `shadow_city.decisions` (fresh model calls only, no cache
hits), rebuilds the exact System One prompt for each, asks every Gemma model on the Gemma
service, and compares the option probabilities.

Metrics per model:
- top1_agreement: Gemma's favourite option equals Gemini's favourite
- top2_contains_gemini_favourite: Gemini's favourite is among Gemma's two most likely options
- mean_tv_distance: mean total-variation distance between the two distributions (0 = identical)
- valid_json_rate, median latency, and wall-clock throughput at the given concurrency

Usage (from the repo root; needs gcloud auth and system-one's venv):
  PYTHONPATH=services/system-one services/system-one/.venv/bin/python ml/distillation/eval_agreement.py \
      --gemma-url https://gemma-....run.app --n 300 --models gemma4:e2b gemma4:e4b gemma3:4b
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import time
from datetime import date
from pathlib import Path

from google.cloud import bigquery, firestore

from app.gemini_decider import SYSTEM_INSTRUCTION, build_prompt, response_schema
from app.gemma import OllamaGemma
from app.models import DecisionRequestItem
from app.personas import PersonaLookup
from app.sampling import normalize_probabilities

PROJECT = "ebc-cloud-dev-03"
RESULTS = Path(__file__).resolve().parent / "results"


def sample_decisions(n: int) -> list[dict]:
    query = f"""
        SELECT request, probabilities
        FROM `{PROJECT}.shadow_city.decisions`
        WHERE decided_by = 'gemini-system-two' AND IFNULL(cache, 'miss') = 'miss'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY logged_at) = 1
        ORDER BY FARM_FINGERPRINT(decision_id)
        LIMIT {n}
    """
    rows = bigquery.Client(project=PROJECT).query(query).result()
    return [{"request": json.loads(r["request"]) if isinstance(r["request"], str) else r["request"],
             "gemini": json.loads(r["probabilities"]) if isinstance(r["probabilities"], str) else r["probabilities"]}
            for r in rows]


class StaticToken:
    def __init__(self):
        self.token = subprocess.run(["gcloud", "auth", "print-identity-token"], check=True,
                                    capture_output=True, text=True).stdout.strip()

    async def get(self) -> str:
        return self.token


def favourite(probs: dict) -> str:
    return max(sorted(probs), key=lambda k: probs[k])


def top2(probs: dict) -> list[str]:
    return sorted(sorted(probs), key=lambda k: probs[k], reverse=True)[:2]


def tv_distance(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)


async def evaluate(model: str, url: str, samples: list[dict], prompts: list[tuple], concurrency: int) -> dict:
    gemma = OllamaGemma(url, model, StaticToken(), timeout_s=300)
    semaphore = asyncio.Semaphore(concurrency)
    rows = []

    async def one(sample, prompt_and_schema, options):
        async with semaphore:
            started = time.perf_counter()
            try:
                raw, _ = await gemma.ask(SYSTEM_INSTRUCTION, *prompt_and_schema)
                probs = {o.value: p for o, p in normalize_probabilities(raw.get("probabilities") or {}, options).items()}
                ok = True
            except Exception as exc:  # invalid JSON, timeout, ...
                probs, ok = {}, False
                print(f"  {model}: {type(exc).__name__}: {str(exc)[:120]}")
            rows.append({"ok": ok, "gemma": probs, "gemini": sample["gemini"],
                         "latency_s": time.perf_counter() - started})

    # Warm up the model so a cold start does not count against latency.
    await one(samples[0], prompts[0][0], prompts[0][1])
    rows.clear()
    wall = time.perf_counter()
    await asyncio.gather(*(one(s, p, o) for s, (p, o) in zip(samples, prompts)))
    wall = time.perf_counter() - wall

    valid = [r for r in rows if r["ok"] and r["gemma"]]
    return {
        "model": model,
        "n": len(rows),
        "valid_json_rate": round(len(valid) / len(rows), 3),
        "top1_agreement": round(sum(favourite(r["gemma"]) == favourite(r["gemini"]) for r in valid) / len(valid), 3),
        "top2_contains_gemini_favourite": round(
            sum(favourite(r["gemini"]) in top2(r["gemma"]) for r in valid) / len(valid), 3),
        "mean_tv_distance": round(statistics.mean(tv_distance(r["gemma"], r["gemini"]) for r in valid), 3),
        "median_latency_s": round(statistics.median(r["latency_s"] for r in rows), 2),
        "throughput_decisions_per_s": round(len(rows) / wall, 2),
        "concurrency": concurrency,
    }


async def main_async(args) -> None:
    samples = sample_decisions(args.n)
    print(f"{len(samples)} Gemini decisions sampled from BigQuery")
    personas = PersonaLookup(firestore.Client(project=PROJECT, database="shadow-city"))
    prompts = []
    for s in samples:
        item = DecisionRequestItem.model_validate(s["request"])
        persona = await personas.get(item.persona_id)
        prompts.append(((build_prompt(item, persona), response_schema(item)), item.options))
    results = []
    for model in args.models:
        print(f"evaluating {model} ...")
        results.append(await evaluate(model, args.gemma_url, samples, prompts, args.concurrency))
        print(json.dumps(results[-1]))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"agreement_{date.today().isoformat()}.json"
    out.write_text(json.dumps({"samples": len(samples), "results": results}, indent=1) + "\n")
    print(f"saved {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemma-url", required=True)
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--models", nargs="+", default=["gemma4:e2b", "gemma4:e4b", "gemma3:4b"])
    parser.add_argument("--concurrency", type=int, default=4)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
