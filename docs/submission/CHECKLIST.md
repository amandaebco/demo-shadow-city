# Submission checklist — Google Cloud AI Builder Cup 2026

Requirements from https://aibuildercup.com/themes.html. Tick each box before submitting.

## The four deliverables

- [ ] **Proposal deck as PDF** — built from `docs/submission/deck.md`, architecture slide from `docs/submission/architecture.png`. Covers problem, community benefit, feasibility, scalability, GCP architecture.
- [ ] **Functional prototype URL** — https://shadow-city.web.app (Firebase Hosting; backend on Cloud Run).
- [ ] **Public demo video, 3 minutes** — recorded from `docs/submission/video-script.md`; YouTube, Vimeo or a public Google Drive link.
- [ ] **Theme stated clearly** — Sustainability & Social Impact (in the form, on slide 1, in the video intro if possible).

## Rules

- [ ] Uses Google AI models — Gemini on Vertex AI (System Two and decisions); Gemma 4 on Cloud Run GPU (System One, live).
- [ ] Deployed on Google Cloud via Cloud Run / Firebase — yes.
- [ ] Everything in English — code, README, deck, video narration and captions.
- [ ] Team of 2–4 working professionals — EBCO Cloud Expert.

## Final checks (on the day)

- [ ] Run `python3 infra/smoke_test.py`: every check passes (22 read-only checks through the public URL).
- [ ] Open the prototype URL in a private/incognito window: map loads, the three demo scenarios and the 5,000-resident scenario open, Find Resident `00954` works, Analyst Report and Verification tabs show content.
- [ ] Video link opens while signed out (truly public).
- [ ] Deck PDF opens, has no `[bracket]` placeholders left, and the closing slide has the prototype and video links.
- [ ] Numbers in the deck match the video narration (both come from the stored demo runs).
- [ ] Do not re-run the frozen demo scenarios after recording.
- [ ] Keep the services up until judging ends; new scenarios are capped at 30 per day and 5,000 residents each.

## Optional after submission

- Turn on `GEMINI_THINKING_LEVEL=low` for System One (−65% cost per decision); it starts a fresh decision cache.
- Distil Gemini into Gemma with the logged decisions (`ml/distillation/`), then switch System One to `DECIDER=gemma`.
