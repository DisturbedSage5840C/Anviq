# Anviq

A private WhatsApp voice coach for Grade 1-3 foundational-literacy-and-numeracy teachers.
Plan, rehearse with three AI children, teach, reflect. Institutions see only anonymous
trends for groups of 20+ teachers.

Built for the hack2skill x ShikshaNext x Anthropic "AI for Foundational Learning" hackathon
(Challenge 3, Teacher Support), by Team BBC (Big Black Claude), Plaksha University.

## What it does

A teacher sends a voice note in Hindi or English and gets a spoken reply back, with no app to
install. Each day has four steps:

1. **Plan** tomorrow's lesson on a topic from the Grade 1-3 FLN curriculum.
2. **Rehearse** it with three AI children who each hold a real misconception, while a silent coach
   scores the teacher's questions against a six-move rubric.
3. **Teach** the class.
4. **Reflect** on how it went, in a minute.

Two more things sit beside the loop. **Ask Anviq** answers a pedagogy question only from the
NISHTHA / NIPUN source documents and cites where; if nothing supports an answer it says so instead
of guessing. The **Day-1 / Day-14 mirror** sets a teacher's first practice question beside their
latest and shows growth as a plant (🌱 🌿 🌳), never a score and never compared with anyone.

Privacy is the design, not an add-on. Audio is never stored, phone numbers are hashed, transcripts
are scrubbed of personal details and deleted on a schedule, and a teacher can export or erase
everything by saying so. Mentors, CRPs and DIET see only anonymous trends for groups of 20 or more
teachers; no view of a single teacher exists anywhere in the code.

## Team

| Who | GitHub | Built |
|---|---|---|
| Marutey Mani | [@DisturbedSage5840C](https://github.com/DisturbedSage5840C) | Platform and privacy: WhatsApp channel, speech, router, Plan / Reflect / Mirror, jobs, web room API, CI, deployment |
| Aadi Batra | [@aadibatra2106](https://github.com/aadibatra2106) | Coaching core: Ask Anviq, the AI children, the rubric-driven coach, the evaluation harness |
| Vansh Awasthi | [@Vansh170806](https://github.com/Vansh170806) | Content and pedagogy: reviewed rubrics, topic map, Hindi and English copy, gold-labelled evaluation sets, corpus manifest |
| Joepaul Thomas | [@jomemer50](https://github.com/jomemer50) | Front ends and QA: the browser web room, the mentor dashboard, device QA checklist, Playwright E2E tests |

## How it fits together

```mermaid
flowchart LR
    T[Teacher on WhatsApp] -->|voice note or text| M[Meta Cloud API]
    V[Visitor in a browser] -->|audio or text + demo code| API
    M -->|signed webhook| API[api: FastAPI]
    API -->|verify, dedupe, rate limit| Q[(Redis queue)]
    Q --> W[worker: arq]
    W -->|speech to text and back| S[Sarvam / Google]
    W -->|route, reply| C[core: router, privacy]
    W -->|send voice and text| M
    C --> DB[(Postgres + pgvector)]
    DB -->|public_trends view, k >= 20| D[Mentor dashboard]
```

Two processes ship from one image: `api` answers Meta fast by queuing the work, `worker` does the
slow part. Details, and what is built versus still to come: [Architecture](docs/architecture.md).

## Try it (judge access)

Fill these in at release; nothing below is live until then.

| Way in | What you need |
|---|---|
| WhatsApp | Scan the QR or message the number, then say "Namaste". Number: _to be added at release_ |
| Browser (no WhatsApp) | Open the [web room](https://35-200-176-62.sslip.io/room/) and enter a demo code (the team issues one) |
| Mentor dashboard | Token-gated; shows only groups of 20+ teachers. URL and token: _to be added at release_ |

The team issues web demo codes (never put one in the repo). A code allows a fixed number of turns
and expires after 7 days:
`docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml run --rm api uv run --no-sync python -m app.web.issue_code --turns 20`.
See the [runbook](docs/runbook.md#web-room).

## Measured results and known limits

Numbers from the last evaluation runs; the full tables and method are in [eval/report.md](eval/report.md).

| What | Result | Against the target |
|---|---|---|
| Out-of-scope questions refused by Ask Anviq | 40 of 40 | Met |
| Coach agreement with the gold labels (Cohen's kappa) | 0.967, on a gold set written by our content lead, not independently adjudicated | Met (target 0.6) |
| AI child stays in character | 98.3% raw, 99.4% after one regeneration, for the Riya persona only (720 turns) | Met for Riya; Aman and Meena not yet run |
| Citations that name the right source | Right course 58.3%; exact module and section 0% (our gold labels number sections differently from the books) | **Not met** (target 95%) |
| In-scope questions wrongly refused | 28% in the last run (22% in an earlier one) | **Not met** (target 5% or less) |
| Cost per teacher-day | About US$0.15, re-priced from 2 teacher-days of test traffic (the stored report figure is US$0.22; see [eval/NOTES.md](eval/NOTES.md)) | **Not met** (the code's target is US$0.12; the pitch deck says US$0.05) |

Known limits:

- Ask Anviq answers only from the ingested NIPUN Bharat and NISHTHA FLN text. Some natural
  questions (for example "ELPS approach" or "place value with bundles") are refused because that
  text has no passage on them.
- The Hindi NISHTHA PDF was extracted with doubled vowel signs; search collapses them, but some
  passages stay garbled.
- The Day-1 / Day-14 mirror needs both practices recorded; the opt-in encrypted mirror clips are not built.
- The WhatsApp demo number runs on an unofficial gateway (Evolution API) for the demo only. It
  can send no template messages, so daily reminders do not work there, and it carries a ban risk
  under WhatsApp's terms. The Meta Cloud API route is wired but waits on business verification.
- The anonymous-trends dashboard enforces k >= 20 in code, but no pilot has run, so there is no
  real cohort data yet.

## Layout

| Path | What lives there |
|---|---|
| `backend/` | FastAPI service: WhatsApp webhook, router, speech, privacy, jobs |
| `infra/` | Local docker-compose and the demo stack for a single cloud VM (Caddy, API, worker, Postgres, Redis) |
| `content/` | Reviewed rubrics, topic map, personas, Hindi/English copy and the Ask corpus manifest |
| `eval/` | Gold-labelled datasets; the harness itself is `backend/app/evaluation/` (see [eval/README.md](eval/README.md)) |
| `dashboard/` | Aggregate-only mentor dashboard (Next.js, static export; k >= 20) |
| `web-room/` | Browser rehearsal room for judges and teachers off the WhatsApp list: plain HTML and JS, hold to talk |
| `e2e/` | Playwright smoke tests for the dashboard and the web room |
| `docs/` | Architecture, privacy, runbook and incident response (see below) |

## Documentation

| Read | When |
|---|---|
| [Architecture](docs/architecture.md) | How the pieces fit, and what is built versus still to come |
| [Data inventory](docs/data-inventory.md) | What we store about a teacher, where, and for how long |
| [DPIA](docs/DPIA.md) | The privacy risks, what reduces them, and what is left |
| [Runbook](docs/runbook.md) | Something is broken and you are on call |
| [Incident response](docs/incident-response.md) | Teacher data may have been exposed |
| Privacy notices: [English](docs/privacy-notice-en.md), [Hindi](docs/privacy-notice-hi.md) | What a teacher is told before they consent |
| [Evaluation report](eval/report.md) | Measured quality, cost and the targets we missed |
| [Submission pack](docs/submission.md) | Demo video script, deck corrections and the release checklist |

## Run locally

```bash
docker compose -f infra/docker-compose.yml up -d      # Postgres + pgvector, Redis
cd backend
cp ../.env.example .env                                # then fill in your own values
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8080
```

Check it is up: `curl localhost:8080/healthz`

## Test and lint

```bash
cd backend
uv run pytest --cov=app --cov-fail-under=80
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

The database tests skip without `DATABASE_URL`; point it at the compose Postgres
(`postgresql+asyncpg://anviq:anviq@localhost:5432/anviq`, after `alembic upgrade head`) to run them.
If port 5432 is taken, start compose with `ANVIQ_PG_PORT=5433` and use that port.

The browser front ends have their own checks from the repository root:

```bash
npm install && npx playwright install chromium
npm run test:e2e                                       # dashboard and web room smoke tests
```

The evaluation runs that need a model key are listed in [eval/README.md](eval/README.md).

## Licence

MIT, see [LICENSE](LICENSE).

## Secrets

Real keys live only in `backend/.env` (gitignored) and in the hosting provider's secret store
(`infra/demo.env` on the demo VM, gitignored). `.env.example` lists variable names, never values. The app refuses to
start if a required secret is missing.
