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

## Clusters share decisions (Layer 6, 2026-10-18)

`services/orchestrator/app/clustering.py` groups residents by usual mode, vehicles and income band,
then k-means on home/work location, cost/time sensitivity and departure time (target 15 per
cluster); the member nearest the centroid is the representative. Measured with
`services/orchestrator/tools/eval_clustering.py` on `pop_s42_n1000`, using each resident's own
Gemini decision from the demo runs: would the group's shared decision have matched it?

| Scenario | Model calls | Saved | Members matching their group's decision | Random groups of the same sizes |
| --- | --- | --- | --- | --- |
| Baseline | 106 | 89% | 89% | 25% |
| Parking +100% | 106 | 89% | 79% | 21% |
| Parking + flood (split by flood signature) | 161 | 84% | 75% | 19% |

Without the flood split, the flood scenario matched 72%; splitting by the full option set instead
saved only 67–73% for little gain. Agreement drops when a policy or event makes members' situations
diverge: the cost of sharing, stated here rather than hidden.

## Distillation result (2026-10-18)

`services/distill` (Cloud Run Job, one NVIDIA L4, `asia-southeast1`): LoRA (r=16, attention only,
5.4M trainable parameters) on Gemma 4 E2B, 2,000 teacher examples from `export_teacher_data.py`,
one epoch, 36 minutes end to end. Evaluated on 200 held-out Gemini decisions never seen in
training, same prompt and metrics before and after tuning:

| Gemma 4 E2B | Valid JSON | Same favourite as Gemini | Gemini's favourite in top 2 | Mean TV distance |
| --- | --- | --- | --- | --- |
| Before tuning | 100% | 63.0% | 86.5% | 0.331 |
| **After distillation** | **100%** | **89.0%** | **100%** | **0.097** |

For scale: Gemini agrees with itself 93% of the time when asked the same question again
(`eval_thinking.py`), so the distilled 2-billion-parameter-class model is within four points of
Gemini's own consistency. The adapter is not yet served; next step: save it, load it in the Gemma
service, and switch System One to `DECIDER=gemma`.
