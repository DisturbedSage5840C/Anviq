# Anviq

A private WhatsApp voice coach for Grade 1-3 foundational-literacy-and-numeracy teachers.
Plan, rehearse with three AI children, teach, reflect. Institutions see only anonymous
trends for groups of 20+ teachers.

Built for the hack2skill x ShikshaNext x Anthropic "AI for Foundational Learning" hackathon
(Challenge 3, Teacher Support), by Team BBC(Big Black Claude), Plaksha University.

## Layout

| Path | What lives there |
|---|---|
| `backend/` | FastAPI service: WhatsApp webhook, router, speech, privacy, jobs |
| `infra/` | Local docker-compose and Fly.io config (Mumbai, `bom`) |
| `content/` | Rubrics, topic map, personas, Hindi/English copy |
| `eval/` | Evaluation harness and datasets |
| `dashboard/` | Aggregate-only mentor dashboard (k >= 20) |
| `web-room/` | Browser fallback for the rehearsal room |
| `docs/` | Architecture, privacy and runbooks |

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

## Secrets

Real keys live only in `backend/.env` (gitignored) and in the hosting provider's secret store
(`fly secrets set`). `.env.example` lists variable names, never values. The app refuses to
start if a required secret is missing.
