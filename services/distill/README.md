# distill

Track A — Layer 5 distillation job: LoRA-tunes Gemma 4 E2B on Gemini's logged System One decisions
and measures agreement with Gemini on held-out decisions before and after tuning.

- Data: `ml/distillation/export_teacher_data.py` writes `data/train.jsonl` and `data/test.jsonl`
  (not committed; regenerate before building).
- Base model: the public Vertex Model Garden bucket, mounted read-only at `/models`.
- Runs as the Cloud Run Job `distill` on one NVIDIA L4 in `asia-southeast1`: `infra/run-distill.sh`.
- Results are JSON lines in the job's logs (`"event": "eval"` and `"event": "done"`).
