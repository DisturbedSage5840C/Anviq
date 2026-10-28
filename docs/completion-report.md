# Anviq: end-to-end completion report

Written 26 Oct 2026, updated 27 Oct 2026 for the final build. Compares three things: the **build plan** (`ANVIQ_BUILD_PLAN.md`), the **idea-submission deck** (`Anviq Hack.pdf`, 11 slides) and **what is actually built and running**. Submission target is **31 Oct 2026, 23:59 IST**.

Status words: **Done** (built, tested, running), **Changed** (built differently from the plan), **Partial**, **Not built**, **Not run** (built but never exercised).

## 1. Headline

- The core product works end to end on the live demo: WhatsApp on a real number (via Evolution), a browser web room for judges, Plan, Rehearse with AI children, Reflect, Ask Anviq with citations, privacy controls, a k≥20 dashboard.
- Backend quality gates are green: 1657 tests pass (183 skipped, mostly database tests that need a local Postgres), ruff, ruff format and mypy are clean. CI also builds the dashboard, and 21 tests check the demo stack's exposure rules (only Caddy is public, secrets are required, the Evolution webhook is blocked from the internet). The demo VM runs the latest build with HTTPS and hardened headers.
- **Two targets are not met or unproven** and must not be claimed to judges: citations (exact section 94.5% in the latest run, 93.8% on average over three runs, target 95%) and the pilot-completion rate (no pilot has run). False refusals (0%) and out-of-scope refusal (100%) are now met. Cost per teacher-day is **not shown to be met**: roughly US$0.13 to 0.15 on Google speech, a list-price estimate from an assumed day just above the US$0.12 target, so do not claim it as met. The demo speech is paid from the Google Cloud trial credit, so no cash is spent.
- **Nothing has been tested with a real teacher yet.** The mini-pilot (28–31 Oct) has not started.
- What remains is mostly people work: the demo video, the updated deck, the submission form, and a few keys and approvals only you can give.

## 2. Plan vs built

| Plan section | Status | Notes |
|---|---|---|
| §1 MVP scope (Moves 1–2, G1–3 numeracy, 3 personas, 12 malrules, Ask, dashboard, privacy) | Done | 12 executable malrules exist (`SUB.*`, `ADD.*`, `PV.*`, `CMP.*`, `WP.*`). Six rubric files `move_01`…`move_06` exist. |
| §2 Architecture and stack | Changed | Meta Cloud API became three adapters (Meta, Twilio, Evolution). Ask retrieval is in-memory BM25, not pgvector + Voyage. Hosting is one GCP VM with Caddy, not Fly + Supabase + Upstash + Vercel. Models are Haiku 5.5 and Sonnet 5.5 as planned. |
| §3 Pedagogy (daily loop, Day-14 mirror, self-rating) | Done | Plan and Reflect work live. Mirror uses 🌱/🌿/🌳 with a demo-cycle mode. Self-rating exists (`core/self_rating.py`). |
| §3 Opt-in encrypted mirror clips | Built, including Day-14 playback | 'save my recordings' / 'stop saving my recordings' consent toggle (consent notice v3), first and latest scored practice recording kept AES-GCM encrypted for 30 days, deleted on opt-out, withdrawal, erasure and expiry, count shown in 'send me my data'. On Day 14 the mirror sends the first and latest kept recording back as voice notes, each under a label (tested with fakes, not yet heard on a real phone). Consent notice v3 needs Vansh's review. |
| §4 Webhook, signature, dedupe, rate limit | Done | Hardened. Evolution webhook uses a shared-secret header and Caddy blocks it from the internet. |
| §4 Speech adapters (Google, Sarvam), confirm-back, benchmark | Done | The demo runs on Google for both listening and speaking (Neural2 voices); Sarvam stays as a switch-back option. Plus metering of speech usage. |
| §4 Router state machine, consent, delete, export, opt-out | Done | Delete confirm flow is in `core/router.py`. |
| §4 AI children, malrule verbalizer, answer guardrail | Done | Fallback sentence tested for every malrule. |
| §4 Coach with one better phrasing | Done | κ 0.975, see §4 for the caveat. |
| §4 Ask Anviq with citations and out-of-scope refusal | Partial | Works, refuses out-of-scope 40/40, false refusals 0%; citation accuracy is 94.5% in the best run, just under the 95% target. |
| §4 Guardrails and PII scrubber | Done | `guardrails/` includes `pii.py`. |
| §4 Cron jobs (retention, cost report, reminders) | Done | Reminders are skipped on Twilio and Evolution (no templates). |
| §4 Web room and demo codes | Done | Served at `/room/`, with a strict CSP. E2E tests written but the Playwright browser is not installed locally, so they have not been run. |
| §5/§6 Data model, k≥20 view, crypto, retention, DPDP | Done | Field encryption, hashed phones, 90-day transcripts, no raw audio unless the teacher opts in (first and latest practice recording, 30 days, encrypted). Dashboard shows no real cohort data. |
| §6 Security checklist | Partial | pip-audit and npm audit are clean. gitleaks was not run locally (not installed). HawkScan has never run (no `HAWK_API_KEY`). |
| §7 Deploy: Fly, Supabase, Vercel, `deploy.yml` | Changed | Removed by design. Replaced by the free demo stack (§7.8). |
| §7.8 Always-on demo on GCP | Done | `https://35-200-176-62.sslip.io`. Trial ends **30 Jan 2027**. |
| §7.2 Meta verified business number | Not done | Skipped on purpose. Meta test WABA fails outbound (131031). Evolution on a real SIM replaces it for the demo. |
| §8 Eval harness | Done | Four runners plus `eval/report.md`. Targets: see §4 below. |
| §9 Mini-pilot (28–31 Oct) and full pilot (2–16 Nov) | Not run | No teachers onboarded. No trust survey. No real κ data from teachers. |
| §10 Schedule | Behind on pilot, ahead on infra | Feature freeze met in effect. |
| §11 Submission package | Partial | Repo, privacy pack and `eval/report.md` exist. Video, updated deck and form are open. |
| §13 Standards (TDD, ≥80% on cores, files under 800 lines) | Done | CI has ruff, mypy, pytest and a dashboard build. `backend/tests/ops/test_deploy_config.py` checks the compose files and Caddyfile. |

## 3. Deck claims vs reality

| Deck slide | What it says | Reality |
|---|---|---|
| Problem | 25 lakh teachers, NISHTHA 3.0, ASER 2024, 13% DIKSHA use | Statistics from sources. Not re-verified in this build. |
| What Anviq is | Plan ~2 min, Rehearse ~5, Teach, Reflect ~3, always-on Ask | Plan, Rehearse, Reflect and Ask all work. Timings are design targets, not measured. |
| Inside a rehearsal | Riya says 45 (7−2 bug), six questioning moves | Riya's malrules work. Rubrics exist for all six moves; Moves 1–2 are the fully scored ones. |
| Who we build for | Sunita plus a CRP/DIET mentor seeing anonymous trends | Dashboard built and k≥20 enforced in code, but fed synthetic data only. |
| User journey | Day 0–14, Day-14 side-by-side, peer circle | Day-14 mirror built. Peer circle not built. |
| What makes it new | Rehearsal not recording; executable misconceptions; grounded coach; mirror not monitor; voice-first on WhatsApp | All real except "grounded" is weaker than claimed (see citations). Voice works on WhatsApp via an unofficial channel. |
| Tech and data flow | STT → Router → Planner/Children/Coach/Ask → Guardrails → TTS; pgvector | Flow is real. Retrieval is BM25, not pgvector. |
| Targets | Misconception ≥95%; κ ≥0.6; citations ≥95%; ≥60% complete 5+ sessions | See §4. |
| Cost footer | ≈ US$0.05 per teacher per day | **Not supported.** Re-priced at roughly US$0.13 to 0.15 on Google speech (list-price estimate). |
| "Runs on any phone with WhatsApp" | | Works on the demo number. Unofficial Evolution link carries ban risk. |

Corrections to make in the deck are already tabulated in `docs/submission.md` ("Deck corrections").

## 4. Measured results (from `eval/report.md` and `eval/NOTES.md`)

| Target | Result | Verdict |
|---|---|---|
| AI child keeps misconception ≥95% | Raw / after one retry, 720 turns each: Riya 98.6% / 99.9%, Aman 99.0% / 99.7%, Meena 99.2% / 99.9% | **Pass for all three, per-rule bar met** (lowest rule 96.7% for each). Meena's two weak rules had been failing mostly because her shy "umm..." pauses were counted as sentence ends; the counter now treats an ellipsis as a pause (commit dfc835b) and all three were re-run. The model was not changed. |
| Coach κ ≥0.6 | 0.975 on 150 turns | **Pass on paper.** The gold set is Vansh's alone. Not independently adjudicated, so do not quote it to judges until it is. |
| Citations ≥95% | Exact section 94.5% (86 of 91 answerable questions) in the latest run; 93.8% mean over three runs (93.4 to 94.5%); right course about 98%. Without the 10 alternate labels we added: 89.0% and 86.8% in two runs | **Not met** (best run one question short). The 10 alternate labels were added by us after seeing results and are not reviewed by a second person; scoring counts a question right if any cited source matches any accepted label. Most misses are broad Hindi questions. We accept this shortfall rather than add more labels after the fact; a review sheet for a second person is in `eval/review/citation_gold_review.md`. |
| Out-of-scope refused | 40 of 40 | **Pass.** |
| False refusals ≤5% | 0% (latest run; 22% before the fixes) | **Met.** Fixes: NCERT Teachers' Handbook (Classes 1-2) added to the corpus, 10 passages searched instead of 6, a larger answer limit with one retry, and a prompt that answers from the closest passages. Trade-off: the 9 of 100 questions the books do not cover are now answered, not refused. See `eval/NOTES.md`. |
| Cost ≤US$0.12 per teacher-day | Roughly US$0.13 to 0.15 on Google speech, estimated from list prices: model US$0.068, voice about US$0.048 (Neural2, about US$16 per million characters), transcription about US$0.01 to 0.03, replaying an assumed day (5 rehearsal turns, 1 plan, 1 reflect, 1 in-scope question). The stored figure US$0.22 is inflated by test traffic. A later change makes the coach answer in one language, which should save about US$0.01 but is not measured | **Not shown to be met.** It sits just above the target, is a list-price estimate, and depends on the assumed day. Deck's US$0.05 is unsupported. The Google Neural2 voices work end to end on the VM (Hindi and English, speech-to-text and text-to-speech). The team lead listened to the samples on 26 Oct 2026 and accepted them for the demo, while noting they sound plainer than Sarvam or ElevenLabs. English transcription was weaker than Hindi in a small probe (confidence about 0.55, against 0.92 for Hindi). |
| Latency p50 ≤10 s, p95 ≤20 s | Measured end to end on 2026-10-27 through the web room (speech-to-text, brain, text-to-speech, response over HTTPS), 45 turns: p50 5.7 s, p95 10.0 s, max 10.2 s. Text p50 5.1 s, voice p50 7.6 s. Run from the demo VM, not a phone on a mobile network; WhatsApp delivery is not included; small sample (`eval/results/latency_e2e.json`). | **Met on this probe.** Do not claim it for phones on slow networks until a device test is done. |
| ≥60% of pilot teachers complete 5+ sessions | No pilot | **Unproven.** Remove it or label it a goal. |
| Trust (≥80% not watched) | No survey | **Unproven.** |

## 5. Added beyond the plan and the deck

- **Evolution WhatsApp channel** on a real SIM, with setup script, compose profile and docs. Demo only, because it breaks WhatsApp's terms.
- **Twilio adapter** (sandbox failed with error 21654, kept as code).
- **BM25 Ask retrieval**, ingest of NIPUN and NISHTHA with per-course page ranges.
- **Cost and usage metering** for models and speech, a model budget, and a daily cost report.
- **Security hardening:** `/docs` and `/openapi.json` closed, HSTS, Permissions-Policy, nosniff, CSP on the web room, Evolution on its own network, dashboard `next` upgraded (0 audit findings).
- **Log redaction `f6b80e4`:** phone numbers no longer appear in worker job logs. Verified live.
- **Web room end-to-end flows** checked, with Ask demo questions that work and ones that get refused.
- **Consent parsing fails closed (27 Oct):** a negated or buried recordings request ("don't save my recordings", a long sentence that happens to contain the phrase) never switches recordings on; the negated form switches them off.
- **Devanagari cleaning (27 Oct):** doubled vowel signs are collapsed when Hindi text is ingested and again when an answer is built, so teachers see clean Hindi. The Hindi NISHTHA passages on the VM were re-ingested on 27 Oct from the source PDF with the new cleaner (903 passages, 417 English and 486 Hindi; passages with doubled vowel signs went from 437 to 0; a table backup was taken first). Some Hindi pages still show doubled or missing consonants (for example 'वीडिययो' for 'वीडियो'), because the PDF's font maps those glyphs wrongly and plain text extraction cannot repair it; only OCR would.
- **Deploy-config tests and a dashboard CI job (27 Oct)**, and a named `TEMPLATELESS_PROVIDERS` set in `worker.py` for channels that cannot send reminders.

## 6. Honest limits to keep

- No real teacher has used it. No pilot data. No 60% completion figure.
- Reminders do not send on Evolution or Twilio (no templates).
- Scanned Hindi pages would need OCR (Tesseract, a download we have not approved). Hindi passages were re-ingested on 27 Oct, but the pages with wrongly mapped consonants stay garbled until OCR is done.
- Mirror clips are captured, encrypted, kept 30 days and deleted on request, and the Day-14 mirror plays the first and latest back in the teacher's own chat. The clip database paths were checked by a standalone smoke script on the VM, not by the pytest suite.
- The latency figure comes from the VM over HTTPS, not from a phone, on 45 turns; the Anthropic credit balance is unknown.
- HawkScan has not run (no `HAWK_API_KEY`). The only secret scan is a grep, not gitleaks.
- Evolution is unofficial. The phone must stay online and charged, and the SIM recharged.
- Dashboard has no real cohort data.
- WhatsApp is open to any sender by design, so judges can reach the demo number without a code. Limits that apply to every sender: consent comes before coaching, 60 messages per hour per sender (duplicates dropped), and 60 paid model steps per sender per day. There is no allow-list and no global cap, so a flood from many different numbers would not be stopped. The web room is the code-gated route.
- Accepted risks: webhook-secret replay, Evolution image pinned by tag not digest, GCP trial ends 30 Jan 2027.
- Credits can run out or be paused: the demo no longer depends on Sarvam (Google speech runs on the trial credit, which ends 2027-01-30), the Anthropic credits expire on 20 Nov 2026 (two days after the Grand Finale), and a model can be suspended for the organisation (Sonnet 5.5 was, briefly). `MODEL_SMART` can be pointed at another model; see `docs/free-demo-deploy.md`.

## 7. What is left

**You (only you can do these):**

0. **Ask the organisers for the exact Anthropic credit balance.** (Sonnet 5.5 and Haiku 5.5 both answered HTTP 200 on 2026-10-27, so the earlier organisation-level suspension is over; asking why it happened is optional.)
1. Record the demo video (3–4 min) and a backup screen recording. The Google Neural2 voices are already accepted for the demo; speak English slowly and clearly on camera, because English transcription is the weaker side.
2. Update the deck using the corrections table. Do not claim the unmet targets.
3. Fill in the submission form. Draft text is available on request.
4. At release, fill the README placeholders: WhatsApp number or QR, dashboard URL and token.
5. Keep the phone online and the SIM recharged. Check Evolution status the day before and on demo day.
6. Back up `FIELD_KEY` and `PHONE_PEPPER` in your password manager. Reset the Meta app secret.
7. Optional: give a `HAWK_API_KEY`, approve the Playwright browser download (about 150 MB), run the friend test from another phone.

**Team:**

- Vansh (**sheet ready, a human is still needed**): a blind labelling sheet for the κ gold set is prepared in `eval/review/kappa_second_labeller.md` and `.csv` (150 turns, no gold labels shown; the key file maps rows back and stays with Vansh). A second person must fill it in; then compare with the gold. Also: have a second person tick through `eval/review/citation_gold_review.md` (the 5 misses and the 10 alternate labels). Relabel the citation gold at course level. Review Hindi copy and mirror thresholds.
- Aadi: **done.** Meena's two weakest rules slipped because the sentence counter split on her hesitation ellipsis ("मैं... "), so 2-sentence replies counted as 3. Fixed in the check (`dfc835b`), all three children re-run: every rule is now at 96.7% or higher. One open nit: in rare injection cases she names the right answer while refusing it (`leaks_correct`, 1 of 240 replies); an optional prompt tweak.
- Joepaul: set a GitHub display name (optional).

**Engineering, optional polish:** done on 27 Oct: the `TEMPLATELESS_PROVIDERS` set, Devanagari normalisation, the dashboard CI build, and compose and Caddyfile tests. Still open: OCR for scanned Hindi pages (needs a download and your OK), and running the clip database tests inside the pytest suite.

**Housekeeping after the demo:** delete the leftover VM backups, tarballs, probe scripts and stopped eval containers.

## 8. Dates

| Date | What |
|---|---|
| 28–31 Oct | Planned mini-pilot (4–6 people). Not started. |
| **31 Oct, 23:59 IST** | **Our submission target** |
| 1 Nov | Official prototype close |
| 2–16 Nov | Planned full pilot |
| 10 Nov | Top 10 announced |
| 18 Nov | Grand Finale |
| 30 Jan 2027 | GCP trial ends. Upgrade or move before then. |
