# Anviq: end-to-end completion report

Written 26 Oct 2026. Compares three things: the **build plan** (`ANVIQ_BUILD_PLAN.md`), the **idea-submission deck** (`Anviq Hack.pdf`, 11 slides) and **what is actually built and running**. Submission target is **31 Oct 2026, 23:59 IST**.

Status words: **Done** (built, tested, running), **Changed** (built differently from the plan), **Partial**, **Not built**, **Not run** (built but never exercised).

## 1. Headline

- The core product works end to end on the live demo: WhatsApp on a real number (via Evolution), a browser web room for judges, Plan, Rehearse with AI children, Reflect, Ask Anviq with citations, privacy controls, a k≥20 dashboard.
- Backend quality gates are green: 1505 tests pass (169 skipped), ruff, ruff format and mypy are clean. The demo VM is up with HTTPS and hardened headers.
- **Four measured targets are not met** and must not be claimed to judges: citations, false refusals, cost per teacher-day, and the pilot-completion rate (no pilot has run).
- **Nothing has been tested with a real teacher yet.** The mini-pilot (28–31 Oct) has not started.
- What remains is mostly people work: the demo video, the updated deck, the submission form, and a few keys and approvals only you can give.

## 2. Plan vs built

| Plan section | Status | Notes |
|---|---|---|
| §1 MVP scope (Moves 1–2, G1–3 numeracy, 3 personas, 12 malrules, Ask, dashboard, privacy) | Done | 12 executable malrules exist (`SUB.*`, `ADD.*`, `PV.*`, `CMP.*`, `WP.*`). Six rubric files `move_01`…`move_06` exist. |
| §2 Architecture and stack | Changed | Meta Cloud API became three adapters (Meta, Twilio, Evolution). Ask retrieval is in-memory BM25, not pgvector + Voyage. Hosting is one GCP VM with Caddy, not Fly + Supabase + Upstash + Vercel. Models are Haiku 5.5 and Sonnet 5.5 as planned. |
| §3 Pedagogy (daily loop, Day-14 mirror, self-rating) | Done | Plan and Reflect work live. Mirror uses 🌱/🌿/🌳 with a demo-cycle mode. Self-rating exists (`core/self_rating.py`). |
| §3 Opt-in encrypted mirror clips | Not built | No consent flag in the schema. Deck must say "planned". |
| §4 Webhook, signature, dedupe, rate limit | Done | Hardened. Evolution webhook uses a shared-secret header and Caddy blocks it from the internet. |
| §4 Speech adapters (Sarvam, Google), confirm-back, benchmark | Done | Plus metering of speech usage. |
| §4 Router state machine, consent, delete, export, opt-out | Done | Delete confirm flow is in `core/router.py`. |
| §4 AI children, malrule verbalizer, answer guardrail | Done | Fallback sentence tested for every malrule. |
| §4 Coach with one better phrasing | Done | κ 0.967, see §4 for the caveat. |
| §4 Ask Anviq with citations and out-of-scope refusal | Partial | Works, refuses out-of-scope 40/40, but citation accuracy and false refusals miss target. |
| §4 Guardrails and PII scrubber | Done | `guardrails/` includes `pii.py`. |
| §4 Cron jobs (retention, cost report, reminders) | Done | Reminders are skipped on Twilio and Evolution (no templates). |
| §4 Web room and demo codes | Done | Served at `/room/`, with a strict CSP. E2E tests written but the Playwright browser is not installed locally, so they have not been run. |
| §5/§6 Data model, k≥20 view, crypto, retention, DPDP | Done | Field encryption, hashed phones, 90-day transcripts, no raw audio. Dashboard shows no real cohort data. |
| §6 Security checklist | Partial | pip-audit and npm audit are clean. gitleaks was not run locally (not installed). HawkScan has never run (no `HAWK_API_KEY`). |
| §7 Deploy: Fly, Supabase, Vercel, `deploy.yml` | Changed | Removed by design. Replaced by the free demo stack (§7.8). |
| §7.8 Always-on demo on GCP | Done | `https://35-200-176-62.sslip.io`. Trial ends **30 Jan 2027**. |
| §7.2 Meta verified business number | Not done | Skipped on purpose. Meta test WABA fails outbound (131031). Evolution on a real SIM replaces it for the demo. |
| §8 Eval harness | Done | Four runners plus `eval/report.md`. Targets: see §4 below. |
| §9 Mini-pilot (28–31 Oct) and full pilot (2–16 Nov) | Not run | No teachers onboarded. No trust survey. No real κ data from teachers. |
| §10 Schedule | Behind on pilot, ahead on infra | Feature freeze met in effect. |
| §11 Submission package | Partial | Repo, privacy pack and `eval/report.md` exist. Video, updated deck and form are open. |
| §13 Standards (TDD, ≥80% on cores, files under 800 lines) | Done | CI has ruff, mypy, pytest. |

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
| Cost footer | ≈ US$0.05 per teacher per day | **Not supported.** Re-priced at about US$0.15. |
| "Runs on any phone with WhatsApp" | | Works on the demo number. Unofficial Evolution link carries ban risk. |

Corrections to make in the deck are already tabulated in `docs/submission.md` ("Deck corrections").

## 4. Measured results (from `eval/report.md` and `eval/NOTES.md`)

| Target | Result | Verdict |
|---|---|---|
| AI child keeps misconception ≥95% | 98.3% raw, 99.4% after one retry, 720 turns | **Pass.** Riya only. Aman and Meena not run. |
| Coach κ ≥0.6 | 0.967 on 150 turns | **Pass on paper.** The gold set is Vansh's alone. Not independently adjudicated, so do not quote it to judges until it is. |
| Citations ≥95% | 59.0% right course (46 of 78 answered), 0% exact section | **Not met.** Gold labels use Module/§ numbers the books do not use, and many numeracy questions are answered from NIPUN Bharat instead of Course 9. |
| Out-of-scope refused | 40 of 40 | **Pass.** |
| False refusals ≤5% | 22% (latest run; 22–28% across runs) | **Not met.** Verified cause: the ingested text lacks fine-grained maths pedagogy ("number line" 0 hits, "place value" 1, "bundle" 1), so the model rightly says the passages do not cover it. See `eval/NOTES.md`. |
| Cost ≤US$0.12 per teacher-day | About US$0.15 re-priced (stored figure US$0.22 is inflated by test traffic) | **Not met.** Deck's US$0.05 is unsupported. |
| Latency p50 ≤10 s, p95 ≤20 s | Model latency only (1.5–3.8 s median). End-to-end not measured. | **Unknown.** |
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

## 6. Honest limits to keep

- No real teacher has used it. No pilot data. No 60% completion figure.
- Reminders do not send on Evolution or Twilio (no templates).
- Evolution is unofficial. The phone must stay online and charged, and the SIM recharged.
- Dashboard has no real cohort data.
- Unknown senders on WhatsApp are not confirmed to be gated. Your own first message got through without a code.
- Accepted risks: webhook-secret replay, Evolution image pinned by tag not digest, GCP trial ends 30 Jan 2027.

## 7. What is left

**You (only you can do these):**

1. Record the demo video (3–4 min) and a backup screen recording.
2. Update the deck using the corrections table. Do not claim the unmet targets.
3. Fill in the submission form. Draft text is available on request.
4. At release, fill the README placeholders: WhatsApp number or QR, dashboard URL and token.
5. Keep the phone online and the SIM recharged. Check Evolution status the day before and on demo day.
6. Back up `FIELD_KEY` and `PHONE_PEPPER` in your password manager. Reset the Meta app secret.
7. Optional: give a `HAWK_API_KEY`, approve the Playwright browser download (about 150 MB), run the friend test from another phone.

**Team:**

- Vansh: have a second person label the κ gold set. Relabel the citation gold at course level. Review Hindi copy and mirror thresholds.
- Aadi: run the character eval for Aman and Meena on the VM.
- Joepaul: set a GitHub display name (optional).

**Engineering, optional polish:** docstrings on the metered speech classes, a `TEMPLATELESS_PROVIDERS` set in `worker.py`, Unicode normalisation, OCR for garbled Hindi pages, a dashboard build step in CI, Caddyfile and compose tests.

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
