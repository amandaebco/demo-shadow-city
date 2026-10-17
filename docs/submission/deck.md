# Shadow City — proposal deck (slide text)

Copy each slide into the PPT, then export to PDF. Values in `[brackets]` come from the final demo run; never fill them with estimates.

## Slide 1 · Title
- Shadow City
- Test a city policy on AI residents before real residents live with it.
- Theme: Sustainability & Social Impact · Google Cloud AI Builder Cup 2026
- [Team name / members]

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
- Example reason: [one real `reason_short` from the demo run]

## Slide 7 · Demo scenario
- Baseline weekday vs. central parking tariff +100% vs. +100% with a North Jakarta tidal flood
- Citywide: travel time [__ → __ min], cost [Rp __ → Rp __], car share [__% → __%]
- Most affected: [kelurahan / income band from the report]

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
- Gemma as System One, distilled from Gemini's logged decisions, on Cloud Run GPU, to cut cost per decision
- Persona clustering: one decision shared by similar residents
- Parallel workers via Pub/Sub for thousands of residents
- Any JAPAC city with OpenStreetMap and open population data

## Slide 11 · Impact
- Planners see distributional effects before rollout: which neighbourhoods and income groups lose time or money.
- Supports fairer, more sustainable transport policy, e.g. shifting trips to transit without hurting low-income commuters.
- Transparent by design: every number traceable, every decision explainable.

## Slide 12 · Limitations & next steps
- Synthetic population; directional results only.
- Next: official population per kelurahan, verifier agent, backtest against Jakarta's Rp1 fare day, Gemma System One.

## Slide 13 · Closing
- Shadow City: rehearse the policy, protect the residents.
- shadow-city.web.app · [repo link] · [demo video link]
