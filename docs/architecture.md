# Architecture

How Anviq is put together, what is built today and what is still to come. This page describes the
repository as it is, and marks every gap.

## The shape

```text
 Teacher (WhatsApp)                         Visitor (browser demo)
   │ voice note / text                        │ audio or text + X-Demo-Code
   ▼                                          ▼
 Meta WhatsApp Cloud API ──signed webhook──► api  (FastAPI, Google Cloud VM Mumbai)
   ▲                                          │  POST /webhook/whatsapp   POST /web/turn
   │ send text / voice                        │  verify, dedupe, rate limit, enqueue
   │                                          ▼
   │                                    Redis (queue, dedupe ids, counters)
   │                                          │
   │                                          ▼
   └───────────────────────────────── worker (arq, same image)
                                         1 download media into memory
                                         2 speech to text         ── Sarvam (Google fallback)
                                         3 scrub, route           ── core/router
                                         4 reply copy             ── content/copy
                                         5 text to speech, encode ── Sarvam, ffmpeg
                                         6 send and persist
                                              │
                                              ▼
                                  Postgres + pgvector (Mumbai)
                       teachers, consents, turns, sessions, mirror clips,
                       demo codes, usage tables, public_trends view
```

Two processes ship from one Docker image: `api` answers Meta in well under a second by queuing the
work, and `worker` does the slow part (speech, thinking, sending). This keeps the webhook inside
Meta's retry window even when a vendor is slow.

## What is built, and what is not

| Area | State | Where |
|---|---|---|
| WhatsApp webhook: signature check, dedupe, per-sender rate limit, enqueue | Built | `app/api/whatsapp_webhook.py`, `app/channel/` |
| Health and readiness probes | Built | `app/api/health.py` |
| Speech adapters (Sarvam, Google), provider switch by config, benchmark harness | Built | `app/speech/` |
| Audio decode and encode (ffmpeg) | Built | `app/channel/audio.py` |
| Router and session state machine, onboarding, consent, delete, export | Built | `app/core/`, `app/privacy/` |
| Daily reminders (opt-in, template messages, every 15 minutes) | Built | `app/channel/reminders.py` |
| Retention purge (hourly), cost digest (08:00 IST) | Built | `app/privacy/retention.py`, `app/ops/cost_report.py` |
| Web rehearsal room API with demo codes | Built | `app/api/web_room.py`, `app/web/` |
| Error reporting with scrubbing | Built (off without `SENTRY_DSN`) | `app/ops/sentry.py` |
| Daily loop: Plan, Reflect, the Day-1/Day-14 mirror | Built | `app/core/planner.py`, `reflect.py`, `mirror.py`, `daily_loop.py` |
| Ask Anviq: grounded answers with citations, refusal when nothing supports one | Built | `app/core/ask/` |
| Rehearse: three AI children, silent coach, week-B self-rating, summary | Built | `app/core/rehearsal*.py`, `self_rating.py`, `coach.py`, `children/` |
| First practice offered at the end of onboarding | Built | `app/core/router.py` (`ONB_FIRST_REHEARSAL`) |
| Model client with per-tier models and guardrail checks | Built (never run against a live model in CI) | `app/llm/`, `app/guardrails/` |
| Nightly aggregates job | **Not yet** | planned in `worker.py` |
| Dashboard data API: `GET /dashboard/trends`, bearer token, `dashboard_ro` connection, `public_trends` only | Built (off until `DASHBOARD_API_TOKEN` and `DASHBOARD_DATABASE_URL` are set) | `app/api/dashboard.py`, `app/dashboard/` |
| Mentor dashboard page | Built (static Next.js export; not yet hosted, and shows synthetic demo rows until the API feed is configured) | `dashboard/` |
| Web room front end | Built (plain HTML and JS, hold to talk; not yet hosted, and needs the API origin in `WEB_ALLOWED_ORIGINS`) | `web-room/` |
| Browser E2E smoke tests | Built | `e2e/`, `playwright.config.ts` |
| Evaluation harness | Built; needs a model key to produce real numbers | `app/evaluation/`, see `eval/README.md` |
| Rubrics for coaching moves 1-6, personas, topic map | Built and reviewed (`status = "reviewed"`, Moves 1-6 each have 6+ positive and 6+ negative bilingual examples; topics mapped to NIPUN LOs and NISHTHA Course 9) | `app/content/rubrics/`, `app/content/topics.toml`, `app/core/children/`, `content/` |
| Opt-in encrypted mirror clips | **Not yet** | the `mirror_clips` table exists; no flow stores one |
| Hindi copy | Built and reviewed | `app/content/copy/hi.toml` |

## Modules (`backend/app/`)

| Module | Responsibility |
|---|---|
| `api/` | HTTP edges only: webhook, web room, health. Thin; no business logic |
| `channel/` | Everything about talking to WhatsApp: signature, message parsing, dedupe and rate limits, the job queue, sending, and the pipeline that ties one inbound message to one reply |
| `core/` | The router and dialogue state machine, intent detection, the teacher store protocol, and the coaching features: planner, reflect, mirror, rehearsal (with its codec and flow), coach, the AI children, Ask Anviq |
| `llm/` | The model client and its ports; the router never talks to a vendor directly |
| `evaluation/` | Offline checks for the quality targets: child character, coach agreement, citations, latency and cost |
| `speech/` | `Transcriber` and `Synthesizer` protocols, Sarvam and Google adapters, voice choice, per-call usage metrics |
| `privacy/` | Field encryption, keyring, retention purge, data export |
| `guardrails/` | The PII scrubber. Runs before anything is stored or handed to an error reporter |
| `db/` | SQLAlchemy stores and Alembic migrations |
| `web/` | Demo codes, the code-issuing command and the web turn |
| `ops/` | Cost report and Sentry setup |
| `content/` | Hindi and English user-facing copy, kept in one place |
| `config.py` | Typed settings from the environment. Refuses to start without required secrets |
| `main.py`, `worker.py` | App factory; arq worker settings and cron jobs |

Dependencies point inward: `api/` uses `core/`, and `core/` does not import `api/`. Adapters
(speech, WhatsApp client, stores) sit behind `Protocol`s so tests use fakes and a provider swap is
a config change.

## A teacher's first days

1. **Onboarding:** language, grade band, then the consent notice. A "yes" is recorded with a digest
   of the exact notice shown, and the teacher is offered a first 60-second practice.
2. **First practice (`ONB_FIRST_REHEARSAL`):** "yes" starts a rehearsal on a starter topic, because a
   new teacher has no plan yet. Anything else goes to the menu; a question is answered; the offer
   lapses after 30 minutes. Nothing starts without consent.
3. **Daily loop:** Plan tomorrow's lesson, rehearse it (the topic comes from the plan), teach,
   reflect. A rehearsal ends after three good turns, six turns, or a stop word.
4. **Week B of the cycle:** the coach first asks the teacher to rate their own question (a plant,
   never a number) and only then shows what it saw, set beside the teacher's rating.

The router is a pure function (`handle(state, text) -> Transition`); `router_brain.py` applies the
database effects under a per-teacher lock and runs the model calls after the commit.

## One turn

1. Teacher sends a voice note. Meta POSTs to `/webhook/whatsapp` with `X-Hub-Signature-256`.
2. `api` verifies the signature over the raw body, drops a repeated message id, applies the
   per-sender limit (60 an hour) and queues the job. It answers 200 quickly. If Redis is down it
   answers 503, so Meta retries instead of the message being lost.
3. `worker` downloads the audio into memory. It is **never written to disk or the database**.
4. Speech to text (Sarvam by default). Audio bytes are dropped.
5. The transcript passes through `guardrails.pii.scrub`, then the router decides what the teacher
   is doing (onboarding, consent, planning, deleting, asking) from the stored state.
   Each step that calls a paid model is first charged to the teacher's daily allowance (60 a day,
   `MAX_MODEL_STEPS_PER_DAY`, counted in Redis by IST date); past it the teacher is asked to come
   back tomorrow and nothing paid runs.
6. The reply is chosen, then synthesised and encoded to OGG/Opus. A failed voice reply still sends
   the text.
7. The reply is sent. Usage counts are recorded for every model call. A practice also keeps its
   own scored questions: one `rehearse` session per practice, and one `turns` row per question with
   the scrubbed text and the coach's criteria. The Day-1/Day-14 mirror reads those rows. They are
   written under the teacher's lock, in the same transaction as the practice state, and only for a
   turn that stands: a turn dropped for a newer one, or arriving after consent was withdrawn,
   leaves nothing. Finishing, ending or restarting a practice closes its session, and the hourly
   retention job closes one the teacher abandoned for a day. Other conversation text is not
   stored, and the usage tables hold no content.

The web room follows the same path from step 4 with a visitor id derived from the demo code, and
returns the reply (text and a WAV) in the HTTP response instead of sending through Meta.

## Data and trust boundaries

- **Postgres** (Supabase, Mumbai) holds personal data, encrypted at rest by the provider, with
  field-level AES-GCM on the reversible phone id and mirror clips. Row level security is on for
  every table.
- **Roles:** `app_rw` for the API and worker, `dashboard_ro` for the aggregate view only, no
  anonymous access.
- **Redis** (Upstash, Mumbai) holds only short-lived coordination data: queue, dedupe ids,
  counters.
- **Keys:** `FIELD_KEY` and `PHONE_PEPPER` exist only in the secret managers and the running
  process. Without them the stored phone data is neither readable nor linkable.
- **Aggregates:** institutions never touch the main tables. The `public_trends` view is a
  security-barrier view with k of at least 20.

What is stored and for how long: [data-inventory.md](data-inventory.md). Risk assessment:
[DPIA.md](DPIA.md).

## Environments

| Env | Backend | Database | WhatsApp |
|---|---|---|---|
| local | `uvicorn` and `arq` against docker-compose Postgres (pgvector) and Redis | local | test number through a tunnel |
| demo | One Google Cloud VM (Mumbai, trial credit) running `infra/docker-compose.demo.yml`: Caddy for HTTPS, `api`, `worker`, Postgres, Redis | Postgres container with a named volume | Meta test number (at most 5 whitelisted phones), plus the web room for everyone else |

There is one deployed environment and it is the demo. The `migrate` container runs
`alembic upgrade head` before the API and worker start, so a failed migration leaves the old
containers serving until it is fixed. Setup and day-to-day commands:
[free-demo-deploy.md](free-demo-deploy.md) and the [runbook](runbook.md).

## CI and deploy

```
PR and main:  ruff check, ruff format --check, mypy, pip-audit, alembic upgrade head,
              pytest with an 80% coverage gate   (Postgres and Redis as service containers)
              gitleaks over full history         (separate job)
```

Details that matter:

- There is no deploy workflow. The VM is updated by hand with `git pull` and
  `docker compose ... up -d --build`, from a commit that is green on `main`. A managed,
  multi-environment pipeline is a decision for after the hackathon.
- CI also gates `app/core`, `app/privacy` and `app/guardrails` at 80% each, on top of the
  overall 80%.
- The database tests need Postgres and skip locally without it; CI runs them.
- Pre-commit runs gitleaks, so a secret is caught before it is committed, not only after a push.

## Operations

Probes: `/healthz` (process up) and `/readyz` (database and Redis reachable). The runbook covers
failures, rollback, rotation and the web room: [runbook.md](runbook.md). Data exposure follows
[incident-response.md](incident-response.md).

## Decisions worth knowing

- **Queue everything slow.** The webhook only verifies and enqueues, so Meta never times out.
- **Config over code for vendors.** Speech provider and model ids are settings, so a vendor outage
  is a secret change, not a deploy.
- **Fail closed on identity.** Missing keys stop the app from starting rather than silently changing
  how phone numbers are hashed.
- **Refuse for free, charge for work.** The web room rejects bad requests before spending a demo
  turn, and refunds a turn only when the refusal happened before any paid work.
- **Scrub at the edges.** The scrubber runs before storage and again before error reports leave the
  process; each lock assumes the other might miss something.
