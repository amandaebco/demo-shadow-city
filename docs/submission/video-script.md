# Shadow City: 3-minute demo video script

About 480 words of narration, roughly 3 minutes 40 seconds with the intro (the rules allow 3 to 4 minutes; stay under 3:50). The screen recording (no audio, 3:06; each scenario plays from 05:30 so the morning commute is visible) starts at the 0:20 point; the news intro is added in editing. Segment start times in the recording are in the "Rec" column.

| Time | Rec | On screen | Narration |
| --- | --- | --- | --- |
| 0:00–0:20 | (intro) | News headlines: parking tariff debate, transit fare study, North Jakarta tidal flooding | "Jakarta keeps debating parking tariffs and transit fares, while tidal floods hit the north. But policies are decided before anyone can see how they change daily commutes, or who ends up paying." |
| 0:20–0:40 | 0:00 | Scenario "Baseline weekday": map, residents moving | "This is Shadow City. Every dot is an AI resident with a home, a job, an income, vehicles and habits, profiled by Gemini. Here is a normal weekday morning: everyone leaves home and heads to work." |
| 0:40–1:05 | 0:18 | Scenario "Central parking +100%"; dot colours shift; comparison vs baseline | "Now we double parking tariffs in central Jakarta. Every resident decides again how to commute. Travel times and costs come from a deterministic engine, not from the AI, so every number is reproducible. About eight points of trips move to public transit, most of them to Transjakarta." |
| 1:05–1:25 | 0:44 | Scenario "Central parking +100% with North Jakarta tidal flood"; northern residents stuck | "Add a tidal flood in North Jakarta on the same day. Routes through the flood slow down, and residents adapt. Some can't: in Cilincing, fifty-six of fifty-nine residents are stuck." |
| 1:25–1:50 | 1:05 | Find Resident `747`; decision panel | "Every decision is explainable. This textile factory operator lives in Pademangan and usually rides a motorcycle. Today that route is flooded: fifty-three minutes, twenty-two thousand rupiah. KRL takes forty-one minutes for three thousand, and stays dry. So: KRL, and here is why, in the model's own words." |
| 1:50–2:15 | 1:29 | Analyst Report tab (winners / losers) | "An analyst agent compares each policy with the baseline. The differences are computed by code; Gemini explains them. Doubling parking costs high-income residents most, but low-income residents lose time. And without a baseline, it refuses to claim an effect." |
| 2:15–2:35 | 1:56 | Verification tab | "A separate verifier checks the simulation itself: homes and ages against official Dukcapil population data, mode share against a cited BPS commuter survey, and Gemini audits a sample of residents for coherent profiles." |
| 2:35–2:50 | 2:17 | Backtest tab | "We also backtest against a real day: Jakarta's Rp1 transit fare. The simulated transit share rises by ten points, the direction the news reported. No official daily ridership was published, so we compare direction only, and say so." |
| 2:50–3:20 | 2:32 | Scenario "Scale: 5,000 residents (clustered)" with the Scale & cost card; then the architecture diagram | "And it scales. Similar residents share one decision: five thousand residents run in about two minutes, with three hundred seventy-seven model calls instead of five thousand, for under a dollar. It runs on Cloud Run, Firebase and Gemini, and Gemma on a Cloud Run GPU, distilled from Gemini to eighty-nine percent agreement, as the next System One. Shadow City: rehearse the policy, protect the residents." |

## Before recording

- Demo scenarios use the official Dukcapil population (`pop_s2026_n1000_r2`): A2 `s_baseline_weekday_c4d9d5`, B2 `s_central_parking_100_3aeda8`, C2 `s_central_parking_100_with_north_jakarta_t_fe362a`, D2 (Rp1 backtest) `s_rp1_fare_day_24_april_2026_e68060`.
- Resident `p_s2026_n1000_r2_00747` in C2 is real: motorcycle 53 min / Rp 22,272, flooded → KRL 41 min / Rp 3,000. Type `747` in Find Resident; the UI shows it as "Resident #747".
- B2 vs baseline: transit share 32.1% → 39.9% (+7.8 pp; Transjakarta +5.7 pp), motorcycle −7.7 pp, average cost +Rp 3,255; high-income cost +Rp 7,123, low-income time +1.1 min. C2: 212 residents stuck; Cilincing 56 of 59. D2: transit share +10.6 pp, direction match.
- All numbers in the narration come from the stored demo runs (`docs/submission/deck.md`). Do not re-run the demo scenarios before recording.
- Upload the video as public (YouTube, Vimeo, or a public Google Drive link) and put the link on the closing slide and in the submission form.
