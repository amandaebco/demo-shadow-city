#!/usr/bin/env python3
"""Export Gemini teacher decisions from BigQuery as chat examples for tuning Gemma.

Each example: the exact System One prompt (system instruction + user prompt with the persona's
habit context) and Gemini's JSON answer (probabilities + reason). Fresh model calls only, one per
decision. About 10% (by a hash of decision_id) is held out as the test set.

Usage (from the repo root):
  PYTHONPATH=services/system-one services/system-one/.venv/bin/python ml/distillation/export_teacher_data.py \
      --out services/distill/data
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from google.cloud import bigquery, firestore

from app.gemini_decider import SYSTEM_INSTRUCTION, build_prompt
from app.models import DecisionRequestItem
from app.personas import PersonaLookup

PROJECT = "ebc-cloud-dev-03"
# reason_short gets a "Sampled X (p=..); model favored Y (p=..). " prefix from System One, not Gemini.
SAMPLED_PREFIX = re.compile(r"^Sampled \S+ \(p=[0-9.]+\); model favored \S+ \(p=[0-9.]+\)\.\s*")


async def main_async(out: Path) -> None:
    query = f"""
        SELECT decision_id, TO_JSON_STRING(request) AS request, TO_JSON_STRING(probabilities) AS probabilities,
               reason_short, MOD(ABS(FARM_FINGERPRINT(decision_id)), 10) = 0 AS is_test
        FROM `{PROJECT}.shadow_city.decisions`
        WHERE decided_by = 'gemini-system-two' AND IFNULL(cache, 'miss') = 'miss'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY logged_at) = 1
    """
    rows = list(bigquery.Client(project=PROJECT).query(query).result())
    personas = PersonaLookup(firestore.Client(project=PROJECT, database="shadow-city"))
    out.mkdir(parents=True, exist_ok=True)
    counts = {"train": 0, "test": 0}
    with open(out / "train.jsonl", "w") as train, open(out / "test.jsonl", "w") as test:
        for r in rows:
            request = json.loads(json.loads(r["request"])) if r["request"].startswith('"') else json.loads(r["request"])
            item = DecisionRequestItem.model_validate(request)
            prompt = build_prompt(item, await personas.get(item.persona_id))
            answer = {"probabilities": json.loads(r["probabilities"]),
                      "reason_short": SAMPLED_PREFIX.sub("", r["reason_short"] or "")}
            example = {"decision_id": r["decision_id"], "system": SYSTEM_INSTRUCTION, "prompt": prompt,
                       "options": [o.value for o in item.options], "answer": answer}
            (test if r["is_test"] else train).write(json.dumps(example, ensure_ascii=False) + "\n")
            counts["test" if r["is_test"] else "train"] += 1
    print(json.dumps(counts))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    asyncio.run(main_async(parser.parse_args().out))


if __name__ == "__main__":
    main()
