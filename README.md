# Anviq

A private WhatsApp voice coach for Grade 1-3 foundational-literacy-and-numeracy teachers.
Plan, rehearse with three AI children, teach, reflect. Institutions see only anonymous
trends for groups of 20+ teachers.

Built for the hack2skill x ShikshaNext x Anthropic "AI for Foundational Learning" hackathon
(Challenge 3, Teacher Support), by Team BBC(Big Black Claude), Plaksha University.

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

Fill these in at release (build plan D14); nothing below is live until then.

| Way in | What you need |
|---|---|
| WhatsApp | Scan the QR or message the number, then say "Namaste". Number: _to be added at release_ |
| Browser (no WhatsApp) | Open the web room and enter a demo code. URL: _to be added at release_ |
| Mentor dashboard | Token-gated; shows only groups of 20+ teachers. URL and token: _to be added at release_ |

The team issues web demo codes (never put one in the repo). A code allows a fixed number of turns
and expires after 7 days:
`docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml run --rm api uv run --no-sync python -m app.web.issue_code --turns 20`.
See the [runbook](docs/runbook.md#web-room).

## Layout

| Path | What lives there |
|---|---|
| `backend/` | FastAPI service: WhatsApp webhook, router, speech, privacy, jobs |
| `infra/` | Local docker-compose and the free always-on demo stack (Caddy, API, worker, Postgres, Redis) |
| `content/` | Rubrics, topic map, personas, Hindi/English copy |
| `eval/` | Evaluation harness and datasets |
| `dashboard/` | Aggregate-only mentor dashboard (k >= 20) |
| `web-room/` | Browser fallback for the rehearsal room |
| `docs/` | Architecture, privacy, runbook and incident response (see below) |

## Documentation

| Read | When |
|---|---|
| [Architecture](docs/architecture.md) | How the pieces fit, and what is built versus still to come |
| [Data inventory](docs/data-inventory.md) | What we store about a teacher, where, and for how long |
| [DPIA](docs/DPIA.md) | The privacy risks, what reduces them, and what is left |
| [Runbook](docs/runbook.md) | Something is broken and you are on call |
| [Incident response](docs/incident-response.md) | Teacher data may have been exposed |

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

## Licence

MIT, see [LICENSE](LICENSE).

## Secrets

Real keys live only in `backend/.env` (gitignored) and in the hosting provider's secret store
(`infra/demo.env` on the demo VM, gitignored). `.env.example` lists variable names, never values. The app refuses to
start if a required secret is missing.
