# distillation

Track A — Gemma as System One (Layer 5, REFERENCE.md §6.3).

## Teacher data

Every Gemini decision is in BigQuery `shadow_city.decisions` with its full request (the engine's
options, persona context) and response (probabilities, chosen option, reason). Fresh Gemini calls,
excluding cache hits: 4,228 as of 2026-10-18.

## Gemma serving

`services/gemma`: Ollama serving `gemma4:e2b`, `gemma4:e4b` and `gemma3:4b` on Cloud Run with one
NVIDIA L4 in `asia-southeast1`. `system-one` uses it with `DECIDER=gemma` (Gemma first, then
Gemini, then the rule mock), thinking mode off.

## Agreement before tuning (2026-10-18)

`eval_agreement.py`: 150 Gemini decisions sampled from BigQuery, the exact System One prompt sent
to each Gemma model, untuned, temperature 0, concurrency 4 on one L4.

| Model | Valid JSON | Same favourite as Gemini | Gemini's favourite in Gemma's top 2 | Mean TV distance | Median latency |
| --- | --- | --- | --- | --- | --- |
| gemma4:e4b | 100% | 50.0% | 83.3% | 0.308 | 2.6 s |
| gemma4:e2b | 100% | 60.7% | 74.7% | 0.310 | 2.7 s |
| gemma3:4b | 100% | 63.3% | 82.0% | 0.286 | 3.6 s |

Raw results: `results/agreement_2026-10-18.json`. Throughput on one L4: about 1.2 decisions per
second (~4,300 per hour). The same number of Gemini decisions costs about $9.9 at the measured
$0.0023 per decision, so Gemma is cheaper whenever the GPU instance costs less than that per hour
(TODO: confirm the current Cloud Run L4 price in asia-southeast1).

**Conclusion:** untuned Gemma is not yet close enough to Gemini to replace it for results, so the
demo keeps `DECIDER=gemini`. Next step: supervised fine-tuning (LoRA) of a Gemma model on the
teacher data, then rerun `eval_agreement.py` on held-out decisions.

## Run

```bash
PYTHONPATH=services/system-one services/system-one/.venv/bin/python ml/distillation/eval_agreement.py \
    --gemma-url "$(gcloud run services describe gemma --project=ebc-cloud-dev-03 --region=asia-southeast1 --format='value(status.url)')" \
    --n 150 --models gemma4:e4b gemma4:e2b gemma3:4b
```

## Cheaper Gemini: thinking level (2026-10-18)

`eval_thinking.py`: 100 logged Gemini decisions re-asked with the same prompt. The `default` arm
re-runs the production configuration, so its agreement is Gemini's own run-to-run variation.

| Arm | Same favourite as logged | Logged favourite in top 2 | Mean TV distance | Thinking tokens | Cost per decision |
| --- | --- | --- | --- | --- | --- |
| default (control) | 93% | 100% | 0.047 | 364 | $0.00202 |
| thinking level `low` | 87% | 100% | 0.067 | 2 | $0.00072 (−65%) |

`gemini-3.8-flash` rejects `minimal`. Raw results: `results/thinking_levels_2026-10-18.json`.
