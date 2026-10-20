# Runbook

What to do when something is broken. Written for whoever is on call at 2 a.m. with SSH access to
the demo VM. Alerts go to Marutey and Aadi.

Anviq runs on one free always-on VM (Oracle Cloud, Mumbai) from `infra/docker-compose.demo.yml`:
`caddy` (HTTPS), `api`, `worker`, `postgres` and `redis`. Setup is in
[free-demo-deploy.md](free-demo-deploy.md). On the VM, from the repo folder, every command below
uses this shorthand:

```bash
DC="docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml"

$DC ps                          # containers and health
$DC logs -f --tail 100 api worker
$DC config --services           # service names
```

Secrets live in `infra/demo.env` (gitignored, mode 600). Print its variable names with
`cut -d= -f1 infra/demo.env`, never its values. Changing a secret takes effect after
`$DC up -d api worker` recreates those containers.

## First look

1. `curl https://<app-host>/healthz` must say `{"status":"ok"}`. If not, the API process is down:
   go to [API will not start](#api-will-not-start).
2. `curl https://<app-host>/readyz`. A 503 names what is down (`redis`, `database`) and never says
   why. Go to [Database is down or full](#database-is-down-or-full) or
   [Redis is down](#redis-is-down).
3. `$DC logs --tail 200 api worker` and look for the lines in the table below.

| Log line | Means | Go to |
|---|---|---|
| `invalid signature` (HTTP 401 on the webhook) | Meta's signature does not match `WA_APP_SECRET` | [Webhook failing](#webhook-failing) |
| `failed to enqueue inbound message` (HTTP 503) | Redis queue unreachable | [Redis is down](#redis-is-down) |
| `sender rate limited; message dropped` | One sender is over 60 messages an hour | Usually nothing; see [Abuse](#abuse-or-a-runaway-sender) |
| `whatsapp_retry attempt=N` | Graph API is slow or flaky | [Meta token expired or Graph is failing](#meta-token-expired-or-graph-is-failing) |
| `could not transcribe voice note` | Speech-to-text failed | [Speech provider is down](#speech-provider-is-down) |
| `voice reply failed` | Text-to-speech failed; the text still went out | [Speech provider is down](#speech-provider-is-down) |
| `daily reminder not sent: <ErrorName>` | One reminder failed; others carried on | [Reminders](#reminders) |
| `retention purge: turns=… demo_codes=…` | The hourly purge ran (healthy) | none |
| `could not refund a web turn` | A demo-code turn was not given back | [Web room](#web-room) |

## Webhook failing

Symptom: teachers say Anviq is silent. Meta shows the webhook as failing, or `$DC logs` shows
`invalid signature` or nothing at all.

1. Is the API up? `/healthz`. If not, [API will not start](#api-will-not-start).
2. `$DC logs api | grep "invalid signature"`. If you see it, `WA_APP_SECRET` differs from
   the Meta app secret. This happens after the secret is regenerated or when a placeholder was left
   in `infra/demo.env`.
   - Copy the current App Secret from the Meta app dashboard (Settings, Basic).
   - Put the value in `WA_APP_SECRET` in `infra/demo.env`, then `$DC up -d api worker`.
3. Verification fails with HTTP 403 when Meta first registers the URL: `WA_VERIFY_TOKEN` differs
   from the token typed into the Meta dashboard. Set them to the same value.
4. No requests arrive at all: confirm the callback URL in Meta is
   `https://<app-host>/webhook/whatsapp` and that the `messages` field is subscribed.
5. HTTP 503 `queue unavailable`: Redis is down. See [Redis is down](#redis-is-down).

Messages Meta could not deliver are retried by Meta for a while, so a short outage loses nothing.
Duplicates are dropped by the dedupe ids (7 day TTL).

## Meta token expired or Graph is failing

Symptom: inbound works but replies never arrive; the worker logs `whatsapp_retry` and then errors.

1. A 24 hour **temporary** token was used by mistake. Production must use a **System User
   permanent token**. In Meta Business Settings, System Users, generate a token with
   `whatsapp_business_messaging` and `whatsapp_business_management`.
2. Put the new token in `WA_ACCESS_TOKEN` in `infra/demo.env`, then `$DC up -d api worker`.
3. If the token is fine, check Meta's status page. The Graph version is config:
   `WA_GRAPH_VERSION` (default `v25.0`). If Meta has retired it, set the supported version.
4. Template messages (reminders) fail separately if a template was rejected or paused. Check the
   template status in Meta; the code expects `daily_plan_reminder_hi` and `daily_plan_reminder_en`.

## Speech provider is down

Symptom: voice notes get "could not understand" replies, or replies arrive as text only.

Switch provider without a deploy:

Set `STT_PROVIDER=google` and `TTS_PROVIDER=google` in `infra/demo.env`, then
`$DC up -d api worker`.

This needs `GOOGLE_SPEECH_API_KEY` to already be set. Set it first if it is not. Quality in Hindi
differs from Sarvam, so switch back when Sarvam recovers (set both to `sarvam` and recreate the
containers the same way).

If both are down, typed messages still work; voice replies degrade to text.

## Anthropic is rate limited or down

Applies once the LLM client is live (it is not yet part of the app, only its settings).

- Model ids are config, so you can drop the coach to the cheaper, faster model without a deploy:
  set `MODEL_SMART=claude-haiku-5-5` in `infra/demo.env` and `$DC up -d api worker`. Revert when
  the limit clears.
- On HTTP 429, back off with jitter and honour `retry-after`. Do not retry in a tight loop; that
  extends the limit.
- The daily cost digest (08:00 IST in the ops chat) shows spend by model. A sudden jump means a
  loop or abuse. See [Abuse](#abuse-or-a-runaway-sender).

## Database is down or full

`/readyz` says `database`. Postgres is the `postgres` container with its data in the `pgdata` volume.

- **Connection errors**: `$DC ps postgres` and `$DC logs --tail 100 postgres`. If it is stopped,
  `$DC up -d postgres`. The API connects as `app_rw` with `APP_DB_PASSWORD`; if that value in
  `infra/demo.env` no longer matches the role's password, rerun `$DC up -d db-roles` to reset it.
- **Disk full** (`df -h /` on the VM; `docker system df`): the largest tables are `turns` and `mirror_clips`. Transcripts older than 90 days
  are removed by the hourly purge; confirm the worker log shows `retention purge:` every hour. If
  it does not, the worker is down: `$DC ps worker` and `$DC restart worker`. If the purge ran and
  the disk is still full, `docker image prune` frees old builds; the Always Free boot volume can be
  enlarged in the Oracle console. Do not delete rows by hand, because `sessions` and aggregates
  depend on the purge's ordering.
- **Bad migration**: the `migrate` container runs `alembic upgrade head` before the API and worker
  start, so a failed migration leaves them not starting. Read it with `$DC logs migrate`.
- **Backups**: the demo stack takes none by itself. Before risky changes, and nightly if the demo
  matters, run
  `$DC exec -T postgres pg_dump -U anviq anviq | gzip > ~/anviq-$(date +%F).sql.gz`
  and copy the file off the VM. Delete dumps older than 7 days so a deleted teacher does not live on
  in them (see [data-inventory.md](data-inventory.md)).
- **Restore**: a restore replays data that teachers may have already asked us to delete. After any restore, re-apply deletions from `deletion_log` (it holds only
  hash prefixes, so match on the `phone_hash` prefix) and tell the incident owner.

## Redis is down

`/readyz` says `redis`, or the webhook returns 503. Inbound messages are refused with 503 so Meta
retries them. `$DC ps redis`, then `$DC up -d redis` if it is stopped; `REDIS_URL` in the compose
file already points at it. Dedupe ids and rate-limit
counters live there, so after a flush a few duplicate deliveries can be processed twice; the cost
is a repeated reply, not data loss.

## API will not start

The app refuses to start when a required secret is missing, by design.

```bash
$DC logs --tail 60 api
```

Common causes: `FIELD_KEY` or `PHONE_PEPPER` missing or not base64 of 32 bytes (the error names
which); `WA_APP_SECRET` or `WA_VERIFY_TOKEN` unset; a malformed `WEB_ALLOWED_ORIGINS`.

Never start the stack without `PHONE_PEPPER`: outside local development a missing key is a hard
failure precisely so a restart cannot silently change every phone hash.

## Updating the demo

There is no automatic deploy: the VM only changes when someone updates it. CI on `main` is the
gate, so update only from a green commit.

```bash
git pull
$DC up -d --build
```

The `migrate` container runs first, then `api`, `worker` and `caddy` are recreated. Smoke test
straight after: `/healthz`, `/readyz`, then one message from a team phone or a web-room code.

## Checking that a deletion worked

Note the teacher's id before they ask to be deleted (for your own test account:
`select id from teachers where …`), then after the deletion:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -c "select set_config('anviq.teacher_id', '<teacher uuid>', false)" \
  -f backend/scripts/verify_deletion.sql
```

It finds every table with a `teacher_id` column from the catalogue, so a table added later is
covered. Silence means zero rows everywhere; otherwise it stops and names the table.

## Rolling back an update

```bash
git log --oneline -5                  # find the last good commit
git checkout <good-commit>
$DC up -d --build
```

Migrations are forward-only in practice. If the bad update included a migration, roll the code
back only if the migration was additive; otherwise fix forward. Return to `main` with
`git checkout main` once the fix is pushed.

## Reminders

The worker claims due teachers every 15 minutes and stamps them as reminded before sending, so a
crash can drop a reminder but never sends one twice. The log line is
`daily reminders: claimed=N sent=N failed=N skipped=N`.

- `failed` is high: see [Meta token expired](#meta-token-expired-or-graph-is-failing) and check the
  template status.
- Nothing logged: the worker is down.
- The job raises "WA_PHONE_NUMBER_ID and WA_ACCESS_TOKEN are required": set both.

## Web room

`POST /web/turn` is the browser demo, gated by demo codes.

- Issue a code from the VM:
  `$DC run --rm api uv run --no-sync python -m app.web.issue_code --turns 20`.
  The code is printed once and only its hash is stored. It expires after 7 days. It must be issued
  with the same `PHONE_PEPPER` as the API, which the container reads from `infra/demo.env`.
- A visitor whose code does not work gets one message for every cause (wrong, expired, used up).
  Issue a new code rather than trying to recover the old one.
- If browser calls fail with a CORS error, add the page's origin to `WEB_ALLOWED_ORIGINS`
  (JSON list or comma-separated) and `$DC up -d api`.
- `could not refund a web turn` means a turn was spent and not given back. It is a one-off; the
  fix is to issue the visitor a fresh code.

## Abuse or a runaway sender

- Per sender: 60 messages an hour, then messages are dropped with a log line and no reply.
- Per demo code: the same 60 an hour, plus the code's own turn budget.
- Per teacher: `MAX_MODEL_STEPS_PER_DAY` (default 60) paid model steps a day, counted by IST date. Each Plan,
  Reflect, Ask, Mirror, practice start and practice turn is one step. Past it the teacher is told to come back
  tomorrow (`daily_limit`) and nothing paid runs; an open practice ends. To lift one teacher's day, delete the
  Redis key `modelsteps:<phone hash hex>:<YYYY-MM-DD>`. If Redis is down the step answers "unavailable"
  and an open practice carries on.
- The cap counts steps, not model calls: one step can make up to three calls (a practice turn asks the coach and
  two children), so the worst-case cost is about three times the setting. Speech to text and voice replies are
  not capped; the 60 messages an hour limit is what bounds them.
- To block a number entirely, raise it with the incident owner; there is no block list yet.
- Watch the daily cost digest. A day that costs several times the trailing average is the signal.

## Load testing

Run from `backend/`, against a throwaway local stack only, never the live demo (the script refuses a host with `prod` in it).

- Webhook ack: `WA_APP_SECRET=... uv run python -m scripts.load_test --base-url http://localhost:8080 webhook`.
  Sends signed messages from fake `91999900xxxx` numbers and times the ack (budget p50 0.5 s, p95 1 s).
  It creates fake teacher rows in that database, and the replies to those numbers fail at Meta. Message ids
  are fresh each run, so a rerun is not swallowed by the 7-day dedupe.
- Whole turn: `LOAD_DEMO_CODES=a,b,c uv run python -m scripts.load_test --base-url ... web`.
  One demo code per simulated teacher, each with at least `--turns` turns left. Budget is the plan's
  p50 10 s, p95 20 s.
- Both modes stay under the 60 messages an hour limit (`--turns` is capped at 60). Exit code 1 means
  a budget was broken; the output names which one.

## Rotating secrets

Rotate any secret that may have been exposed immediately, then write it up in
[incident-response.md](incident-response.md).

| Secret | How | Side effects |
|---|---|---|
| `WA_ACCESS_TOKEN`, `WA_APP_SECRET`, `WA_VERIFY_TOKEN` | Generate in Meta, then update `infra/demo.env` | Recreate containers; update the Meta webhook if the verify token changed |
| `SARVAM_API_KEY`, `GOOGLE_SPEECH_API_KEY`, `ANTHROPIC_API_KEY` | New key in the vendor console, update `infra/demo.env`, then revoke the old key | Recreate containers |
| `SENTRY_DSN`, `OPS_WEBHOOK_URL` | New value from the provider, update `infra/demo.env`, revoke the old one | Recreate containers. The webhook URL is a credential: anyone with it can post to the ops chat |
| `APP_DB_PASSWORD`, `POSTGRES_PASSWORD` | New value in `infra/demo.env`, `$DC up -d db-roles`, then `$DC up -d api worker` (the Postgres superuser password also needs `ALTER USER anviq PASSWORD '...'` inside the container) | Recreate containers |
| `FIELD_KEY` | **Needs a scripted re-key.** See below | Do not just change it: stored ciphertext becomes unreadable |
| `PHONE_PEPPER` | **Needs a scripted re-hash.** See below | Invalidates all issued demo codes and changes per-sender rate-limit keys |

After changing `infra/demo.env`, run `$DC up -d api worker` and check `/readyz`.

### `FIELD_KEY` and `PHONE_PEPPER` (not yet automated)

Neither key carries a version, so changing the value in place breaks every row that was written
with the old one. There is **no rotation script yet**. Until there is, the safe procedure is a
one-off maintenance task, run during a quiet window with a database snapshot taken first:

1. Take a `pg_dump` (see Database is down or full) and note the time.
2. For `FIELD_KEY`: read each `teachers.wa_id_enc` and `mirror_clips.audio_enc`, decrypt with the
   old key, encrypt with the new key, write back in one transaction.
3. For `PHONE_PEPPER`: for each teacher, decrypt `wa_id_enc`, recompute `phone_hash` with the new
   pepper, write back in the same transaction. The WhatsApp id is the phone number, so this is
   possible without asking anyone.
4. Set the new key in `infra/demo.env` immediately after the transaction commits, and recreate the containers.
5. Re-issue any outstanding web demo codes.

Building and testing this script is an open item in the [data inventory](data-inventory.md#known-gaps).
A key that is lost, rather than rotated, makes the affected data unrecoverable: store both keys in
the team's secret manager as well as on the VM.

## After any incident

Write down what happened, what you did and what would have caught it sooner. If personal data may
have been exposed, stop and follow [incident-response.md](incident-response.md) first; the
reporting clock starts when you become aware.
