# Shadow City — 3-minute demo video script

About 430 words of narration, roughly 3 minutes at a normal pace. Record each segment separately and stitch them. Use pre-run scenario results so nothing waits on a live run.

| Time | On screen | Narration |
| --- | --- | --- |
| 0:00–0:25 | News headlines: parking tariff debate, transit fare study, North Jakarta tidal flooding | "Jakarta keeps debating parking tariffs and transit fares, while tidal floods hit the north. But a policy is usually decided before anyone can see how it changes millions of daily commutes, or who ends up paying for it." |
| 0:25–0:50 | Shadow City map, baseline, residents moving | "This is Shadow City. Every dot is an AI resident with a home, a job, an income, vehicles and habits. Gemini created their profiles. Here is a normal weekday, from five in the morning to ten at night." |
| 0:50–1:20 | Select the central parking +100% scenario and run it; dot colours shift | "Now we double parking tariffs in central Jakarta. Each resident decides again how to commute. The travel times and costs come from a deterministic engine, not from the AI, so every number is reproducible. Watch the modes shift." |
| 1:20–1:45 | Add the North Jakarta tidal flood; northern residents get stuck | "Add a tidal flood in North Jakarta on the same day. Routes through the flood slow down or close, and residents adapt. Some can't." |
| 1:45–2:10 | Click resident `p_s42_n1000_00954` in the parking + flood scenario and show the decision panel | "Every decision is explainable. This logistics supervisor depends on a motorcycle. Today the motorcycle route is flooded, sixty-five minutes and twenty-five thousand rupiah. KRL takes seventy-five minutes for three thousand, and stays dry. So: KRL, and here is the reason, in the model's own words." |
| 2:10–2:35 | Comparison panel and analyst report (winners / losers) | "Then an analyst agent compares each policy with the baseline. The differences are computed by code, and Gemini explains them. Doubling parking moves eight points of trips to Transjakarta. High-income residents pay most, low-income residents lose time. Add the flood, and in Cilincing twenty-six of twenty-nine residents are stuck." |
| 2:35–3:00 | Architecture diagram, cost per decision, Gemma roadmap | "It runs on Cloud Run, Firebase and Gemini on Vertex AI. A decision costs about a fifth of a cent, and replays are free from cache. Next, we distil Gemini into Gemma to scale to whole cities, across JAPAC. Shadow City: rehearse the policy, protect the residents." |

## Before recording

- The 1:45–2:10 segment needs a way to click a resident and see their decision. If the frontend has no evidence-chain panel yet, show one decision's input and reason another way; keep the narration.
- The 1:45 example is real: resident `p_s42_n1000_00954` in `s_central_parking_100_with_north_jakarta_t_78f06b` (motorcycle 65 min / Rp 25,465, flooded → KRL 75 min / Rp 3,000). If the demo is re-run with different settings, check the numbers again.
- Upload the video as public (YouTube, Vimeo, or a public Google Drive link) and put the link on the closing slide and in the submission form.
