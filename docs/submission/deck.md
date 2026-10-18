# Shadow City — proposal deck (slide text)

Copy each slide into the PPT, then export to PDF. Numbers come from the demo run on 2026-10-18 (seed 42, 1,000 residents): baseline `s_baseline_weekday_ea7247`, parking `s_central_parking_100_af902a`, parking + flood `s_central_parking_100_with_north_jakarta_t_78f06b`. Remaining `[brackets]` are for the team to fill.

## Slide 1 · Title
- Shadow City
- Test a city policy on AI residents before real residents live with it.
- Theme: Sustainability & Social Impact · Google Cloud AI Builder Cup 2026
- Team EBCO Cloud Expert

## Slide 2 · The problem
- Jakarta debates parking tariffs and transit fares, and faces tidal flooding in the north.
- Policies are decided without a way to test, before rollout, how daily commutes change.
- The key question nobody can answer in advance: who carries the cost?

## Slide 3 · Our answer
- A "shadow" Jakarta of AI residents, each with a home, a job, an income, vehicles and habits.
- Run a policy, watch residents adapt their commute, compare against a baseline.
- See winners and losers by neighbourhood (kelurahan) and income band, in minutes.

## Slide 4 · How it works
1. Generate residents: seeded skeleton + Gemini behavioural profile
2. Simulate a weekday: 204 ticks of 5 minutes, deterministic engine
3. Decide: each resident's mode choice, with probabilities and a reason
4. Compare: policy vs baseline, same seed, same population
5. Explain: Gemini analyst report — headline, winners, losers, recommendations

## Slide 5 · AI decides, code computes
- Gemini decides and explains. It never computes travel time, cost or flooding.
- The engine computes every physical number; code computes every difference between scenarios.
- The report may only quote numbers it was given; without a baseline it cannot claim a policy effect.

## Slide 6 · Every decision is explainable
- Each decision is logged: inputs, option probabilities, chosen mode, model, cost.
- Residents remember (e.g. "stuck in flood near Pluit yesterday") and keep habits; they switch only when another option is clearly better.
- Real example (parking + flood run): a logistics supervisor who depends on a motorcycle. Motorcycle: 65 min, Rp 25,465, route flooded. KRL: 75 min, Rp 3,000, dry. Chose KRL.
- Reason, in Gemini's words: "Motorcycle route is flooded and parking costs are up. KRL is slightly slower but safe from floods and very cheap."

## Slide 7 · Demo scenario
- Baseline weekday vs. central parking tariff +100% vs. +100% with a North Jakarta tidal flood
- 1,000 residents, same seed and population in all three runs; differences computed by code

| | Baseline | Parking +100% | Parking +100% + flood |
| --- | --- | --- | --- |
| Avg travel time | 39.1 min | 40.0 min | 44.3 min |
| Avg trip cost | Rp 18,337 | Rp 21,531 | Rp 20,868 |
| Motorcycle share | 34.2% | 24.6% (−9.6 pp) | 22.5% (−11.7 pp) |
| Transjakarta share | 23.7% | 31.9% (+8.2 pp) | 31.9% (+8.2 pp) |
| Residents stuck | 0 | 0 | 160 |

- Parking +100%: cost rises most for high-income residents (+Rp 9,705 per trip) and barely for low-income residents (+Rp 205), but low and lower-middle income residents lose 1.9–2.2 minutes per trip.
- Add the flood: Tanjung Priok, Cilincing and Penjaringan lose 21–23 minutes per trip; in Cilincing 26 of 29 residents are stuck.

## Slide 8 · Architecture on Google Cloud
- Frontend: Next.js on Firebase Hosting (live map + report)
- Orchestrator: FastAPI on Cloud Run (scenarios, population, comparison, analyst)
- System One: FastAPI on Cloud Run (per-resident decisions, decision cache)
- Gemini on Vertex AI · Firestore · Pub/Sub · Cloud Build CI
- Diagram: the mermaid diagram in the root README

## Slide 9 · Feasibility: it runs today
- Live prototype: shadow-city.web.app
- Measured cost: ~$0.0023 per decision, $0.022 per 50 generated residents
- Re-running a scenario replays identical decisions from cache: zero model cost, seconds instead of minutes
- Written interface contract between two parallel tracks; CI on every merge request

## Slide 10 · Scalability
- Gemma as System One is already live on a Cloud Run L4 GPU (Singapore), behind the same API
- Untuned Gemma vs Gemini on 150 logged decisions: 100% valid structured output; same favourite option 50–63%; Gemini's favourite in Gemma's top two 75–83%
- Next: distil Gemini into Gemma with 4,228 logged teacher decisions, then switch System One to Gemma
- Cheaper Gemini today: thinking level `low` cuts cost per decision by 65% ($0.0020 → $0.0007) while keeping the same favourite in 87% of 100 logged decisions (Gemini agrees with itself 93% of the time)
- Persona clustering: one decision shared by similar residents
- Parallel workers via Pub/Sub for thousands of residents
- Any JAPAC city with OpenStreetMap and open population data

## Slide 11 · Impact
- Planners see distributional effects before rollout: which neighbourhoods and income groups lose time or money.
- Supports fairer, more sustainable transport policy. In our demo, doubling parking moves 8 points of trips to Transjakarta, while showing that low-income residents pay little more but lose time, and that a flood on the same day strands most of coastal Cilincing.
- Transparent by design: every number traceable, every decision explainable.

## Slide 12 · Limitations & next steps
- Synthetic population; directional results only.
- Next: official population per kelurahan, verifier agent, backtest against Jakarta's Rp1 fare day, Gemma System One.

## Slide 13 · Closing
- Shadow City: rehearse the policy, protect the residents.
- shadow-city.web.app · [repo link] · [demo video link]
