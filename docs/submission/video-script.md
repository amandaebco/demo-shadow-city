# Shadow City — 3-minute demo video script

About 480 words of narration, roughly 3 minutes 20 seconds at a normal pace (the rules allow 3 to 4 minutes; stay under 3:50). Record each segment separately and stitch them. Open https://shadow-city.web.app once before recording so every demo scenario is cached and switching is instant.

| Time | On screen | Narration |
| --- | --- | --- |
| 0:00–0:20 | News headlines: parking tariff debate, transit fare study, North Jakarta tidal flooding | "Jakarta keeps debating parking tariffs and transit fares, while tidal floods hit the north. But policies are decided before anyone can see how they change daily commutes, or who ends up paying." |
| 0:20–0:40 | Scenario "Baseline weekday": map, residents moving | "This is Shadow City. Every dot is an AI resident with a home, a job, an income, vehicles and habits, profiled by Gemini. Here is a normal weekday, from five in the morning to ten at night." |
| 0:40–1:05 | Scenario "Central parking +100%"; dot colours shift; comparison vs baseline | "Now we double parking tariffs in central Jakarta. Every resident decides again how to commute. Travel times and costs come from a deterministic engine, not from the AI, so every number is reproducible. About eight points of trips move to Transjakarta." |
| 1:05–1:25 | Scenario "Central parking +100% with North Jakarta tidal flood"; northern residents stuck | "Add a tidal flood in North Jakarta on the same day. Routes through the flood slow down, and residents adapt. Some can't: in Cilincing, twenty-six of twenty-nine residents are stuck." |
| 1:25–1:50 | Find Resident `00954`; decision panel | "Every decision is explainable. This logistics supervisor depends on a motorcycle. Today that route is flooded: sixty-five minutes, twenty-five thousand rupiah. KRL takes seventy-five minutes for three thousand, and stays dry. So: KRL, and here is why, in the model's own words." |
| 1:50–2:15 | Analyst Report tab (winners / losers) | "An analyst agent compares each policy with the baseline. The differences are computed by code; Gemini explains them. Doubling parking costs high-income residents most, but low-income residents lose time. And without a baseline, it refuses to claim an effect." |
| 2:15–2:35 | Verification tab | "A separate verifier checks the simulation itself: homes and ages against official Dukcapil population data, mode share against a cited BPS commuter survey. It even flags an implausible resident." |
| 2:35–2:50 | Backtest tab | "We also backtest against a real day: Jakarta's Rp1 transit fare. The simulated transit share rises, the direction the news reported. No official daily ridership was published, so we compare direction only, and say so." |
| 2:50–3:20 | Scenario "Scale: 5,000 residents (clustered)" with the Scale & cost card; then the architecture diagram | "And it scales. Similar residents share one decision: five thousand residents run in about two minutes, with three hundred seventy-seven model calls instead of five thousand, for under a dollar. It runs on Cloud Run, Firebase and Gemini, and Gemma on a Cloud Run GPU, distilled from Gemini to eighty-nine percent agreement, as the next System One. Shadow City: rehearse the policy, protect the residents." |

## Before recording

- Resident `p_s42_n1000_00954` in `s_central_parking_100_with_north_jakarta_t_78f06b` is real: motorcycle 65 min / Rp 25,465, flooded → KRL 75 min / Rp 3,000. Type `00954` in Find Resident.
- All numbers in the narration come from the stored demo runs (`docs/submission/deck.md`). Do not re-run the demo scenarios before recording.
- If the Rp1 backtest panel is live by then, you may add to the 2:15 segment: "We also backtest against Jakarta's Rp1 fare day: the simulated transit share moves in the direction reported." Only say it if the panel shows "Direction match: Yes".
- Upload the video as public (YouTube, Vimeo, or a public Google Drive link) and put the link on the closing slide and in the submission form.
