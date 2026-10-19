# Architecture

How Anviq is put together, what is built today and what is still to come. This page describes the
repository as it is, and marks every gap.

## The shape

```text
 Teacher (WhatsApp)                         Visitor (browser demo)
   │ voice note / text                        │ audio or text + X-Demo-Code
   ▼                                          ▼
 Meta WhatsApp Cloud API ──signed webhook──► api  (FastAPI, Oracle VM Mumbai)
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
| Planner, Coach, AI children and malrules, Ask Anviq (RAG), guardrail checks | **Not yet** (LLM client and prompts are other people's work) | planned `app/llm/`, `app/core/coach.py`, `app/core/ask/` |
| Nightly aggregates job | **Not yet** | planned in `worker.py` |
| Dashboard data API: `GET /dashboard/trends`, bearer token, `dashboard_ro` connection, `public_trends` only | Built (off until `DASHBOARD_API_TOKEN` and `DASHBOARD_DATABASE_URL` are set) | `app/api/dashboard.py`, `app/dashboard/` |
| Mentor dashboard page | **Not yet** | `dashboard/` is empty; the API it calls exists |
| Web room front end | **Not yet** | `web-room/` is empty; the API it calls exists |
| Evaluation harness and datasets | **Not yet** | `eval/` is empty |
| Rubrics, personas, topic map | **Not yet** | `content/` is empty |

## Modules (`backend/app/`)

| Module | Responsibility |
|---|---|
| `api/` | HTTP edges only: webhook, web room, health. Thin; no business logic |
| `channel/` | Everything about talking to WhatsApp: signature, message parsing, dedupe and rate limits, the job queue, sending, and the pipeline that ties one inbound message to one reply |
| `core/` | The router and dialogue state machine, intent detection, the teacher store protocol |
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

## One turn

1. Teacher sends a voice note. Meta POSTs to `/webhook/whatsapp` with `X-Hub-Signature-256`.
2. `api` verifies the signature over the raw body, drops a repeated message id, applies the
   per-sender limit (60 an hour) and queues the job. It answers 200 quickly. If Redis is down it
   answers 503, so Meta retries instead of the message being lost.
3. `worker` downloads the audio into memory. It is **never written to disk or the database**.
4. Speech to text (Sarvam by default). Audio bytes are dropped.
5. The transcript passes through `guardrails.pii.scrub`, then the router decides what the teacher
   is doing (onboarding, consent, planning, deleting, asking) from the stored state.
6. The reply is chosen, then synthesised and encoded to OGG/Opus. A failed voice reply still sends
   the text.
7. The reply is sent and the turn is persisted: scrubbed text, results, latency, usage counts.
   Usage tables hold no content.

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
| demo | One free Oracle Cloud VM (Mumbai) running `infra/docker-compose.demo.yml`: Caddy for HTTPS, `api`, `worker`, Postgres, Redis | Postgres container with a named volume | Meta test number (at most 5 whitelisted phones), plus the web room for everyone else |

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
