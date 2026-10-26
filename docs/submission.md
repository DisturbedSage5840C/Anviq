# Submission pack: video script, deck corrections, release checklist

For the hack2skill Build round (deadline 31 Oct 2026, 23:59 IST). Nothing here contains a demo
code, a token or a phone number; those are added by hand at release.

## 1. Demo video (3 to 4 minutes)

Record the browser web room first (it always works), then add a short WhatsApp clip if the
Evolution status is `open`. Never show `infra/demo.env`, a demo code, a terminal with a
long digit string, or the paired phone number.

| Time | On screen | Say (plain, one sentence each) |
|---|---|---|
| 0:00 | Title card: Anviq | A WhatsApp voice coach for Grade 1 to 3 teachers. Plan, rehearse, teach, reflect. |
| 0:15 | Web room, first "Namaste", consent | A teacher agrees to the privacy notice before anything is stored. Audio is never kept. |
| 0:35 | Plan: type a topic (for example place value) | The coach plans tomorrow's lesson in a minute. |
| 1:00 | Rehearse: Riya answers in character; teacher asks "How did you get 45?" | Three AI children each hold one real misconception. The teacher practises the questions that uncover it. |
| 1:45 | Say "enough"; coach feedback appears | A silent coach scored the questions against a six-move rubric: the best question and one line to remember. |
| 2:05 | Reflect: what went well, one thing to try | A one-minute reflection after class. |
| 2:25 | Ask: "How can I help children who struggle to read fluently?" | Ask Anviq answers only from the NIPUN Bharat and NISHTHA books, and names the section it used. |
| 2:50 | Ask: "What is my salary after transfer?" (refused) | If the books do not support an answer, it says so instead of guessing. |
| 3:10 | Voice turn: hold to talk, spoken reply plays | Hindi or English, voice in and voice out. |
| 3:30 | Slide: privacy and honest numbers (section 2 below) | Mentors only see anonymous trends for groups of 20 or more. Here is what we measured and what we missed. |
| 3:50 | End card: repo link | Thank you. |

Use reading and letter-sound questions for the in-scope Ask example. Natural maths questions such
as "ELPS" or "place value with bundles" are refused because the ingested text has no passage on
them, so avoid them on camera. The Day-1 / Day-14 mirror needs two recorded practices; only show it
if you have rehearsed two sessions on the same demo account beforehand.

## 2. Deck corrections (slide text to change so claims match the evidence)

| Claim in the deck | Change it to | Evidence |
|---|---|---|
| Cost about US$0.05 per teacher-day | About US$0.15 per teacher-day, with speech about a third of it; a cheaper voice or a volume plan lowers it | `eval/NOTES.md`, cost section |
| 95% or more of citations correct | Measured on 91 answerable questions: exact section 94.5% in the latest run, 93.8% on average over three runs (93.4 to 94.5%), right course about 98%. 10 of the accepted labels were added by us after seeing results and are not reviewed by a second person. State the target as not yet met (the best run was one question short) | `eval/report.md` |
| Out-of-scope refused, 5% or fewer false refusals | Out-of-scope refused 40 of 40. In-scope wrongly refused 0% in the latest run (22% before the fixes). Met. Nine of our 100 questions are not covered by the books; those are now answered from the nearest passages, not refused | `eval/report.md` |
| Coach agreement kappa 0.6 or more | 0.975 on our gold set, which our content lead wrote; say "not independently adjudicated" | `eval/datasets/gold_turns.jsonl` |
| Children keep their misconception 95% or more | 98.3% raw (99.4% after one regeneration) for the Riya persona, 720 turns; Aman and Meena not yet run | `eval/report.md` |
| 60% of pilot teachers complete 5+ sessions | Remove or label as a pilot goal; no pilot has run | none yet |
| Opt-in encrypted Day-14 mirror clips | Label as planned, not built. The text mirror is built | `docs/architecture.md` |
| Trends sent to DIET at k of 20 or more | Built and enforced in code and the database view; no real cohort data yet | `docs/data-inventory.md` |
| Works on WhatsApp | Works in the web room today. The WhatsApp demo number uses an unofficial gateway for the demo (ban risk, no reminders). The official route waits on Meta business verification | `docs/free-demo-deploy.md` section 6 |

## 3. Privacy pack (already in the repo)

[DPIA](DPIA.md), [data inventory](data-inventory.md), [privacy notice in English](privacy-notice-en.md) and [in Hindi](privacy-notice-hi.md), [incident response](incident-response.md). Submit these links with the repo.

## 4. Release checklist (do these by hand)

1. The day before and on demo day, on the VM: `python3 infra/demo/evolution_setup.py status` must say `connection: open`. If it does not, re-pair with the `pair` command and keep the phone online and the SIM recharged.
2. Issue judge codes on the VM only (`python -m app.web.issue_code --turns 20`) and send them to the organisers directly; never commit one.
3. Fill the README "Try it" table: WhatsApp number or QR, and the dashboard URL and token. Do not commit them if they are secrets.
4. Keep a screen recording of the web room as a fallback in case WhatsApp is down.
5. Back up `FIELD_KEY` and `PHONE_PEPPER` from `infra/demo.env` in your password manager (never in chat) and reset the Meta app secret.
6. After the demo, delete the leftover files and stopped containers on the VM, and remember the GCP trial ends 2027-01-30.
