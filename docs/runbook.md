# Runbook

What to do when something is broken. Written for whoever is on call at 2 a.m. with a phone and
the Fly CLI. Alerts go to Marutey and Aadi.

Apps: `anviq-staging` and `anviq-prod` (Fly, Mumbai). Each runs two process groups: `api` and
`worker`. Replace `-a anviq-prod` with `-a anviq-staging` to practise on staging first.

```bash
fly status -a anviq-prod                 # machines and health checks
fly logs   -a anviq-prod                 # both processes; add --machine <id> to narrow
fly secrets list -a anviq-prod           # names and digests only, never values
```

## First look

1. `curl https://<app-host>/healthz` must say `{"status":"ok"}`. If not, the API process is down:
   go to [API will not start](#api-will-not-start).
2. `curl https://<app-host>/readyz`. A 503 names what is down (`redis`, `database`) and never says
   why. Go to [Database is down or full](#database-is-down-or-full) or
   [Redis is down](#redis-is-down).
3. `fly logs -a anviq-prod` and look for the lines in the table below.

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

Symptom: teachers say Anviq is silent. Meta shows the webhook as failing, or `fly logs` shows
`invalid signature` or nothing at all.

1. Is the API up? `/healthz`. If not, [API will not start](#api-will-not-start).
2. `fly logs -a anviq-prod | grep "invalid signature"`. If you see it, `WA_APP_SECRET` differs from
   the Meta app secret. This happens after the secret is regenerated, or when staging and prod
   secrets were swapped.
   - Copy the current App Secret from the Meta app dashboard (Settings, Basic).
   - `fly secrets set WA_APP_SECRET=<value> -a anviq-prod` (restarts the machines).
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
2. `fly secrets set WA_ACCESS_TOKEN=<new token> -a anviq-prod`.
3. If the token is fine, check Meta's status page. The Graph version is config:
   `WA_GRAPH_VERSION` (default `v25.0`). If Meta has retired it, set the supported version.
4. Template messages (reminders) fail separately if a template was rejected or paused. Check the
   template status in Meta; the code expects `daily_plan_reminder_hi` and `daily_plan_reminder_en`.

## Speech provider is down

Symptom: voice notes get "could not understand" replies, or replies arrive as text only.

Switch provider without a deploy:

```bash
fly secrets set STT_PROVIDER=google TTS_PROVIDER=google -a anviq-prod
```

This needs `GOOGLE_SPEECH_API_KEY` to already be set. Set it first if it is not. Quality in Hindi
differs from Sarvam, so switch back when Sarvam recovers:
`fly secrets set STT_PROVIDER=sarvam TTS_PROVIDER=sarvam -a anviq-prod`.

If both are down, typed messages still work; voice replies degrade to text.

## Anthropic is rate limited or down

Applies once the LLM client is live (it is not yet part of the app, only its settings).

- Model ids are config, so you can drop the coach to the cheaper, faster model without a deploy:
  `fly secrets set MODEL_SMART=claude-haiku-5-5 -a anviq-prod`. Revert when the limit clears.
- On HTTP 429, back off with jitter and honour `retry-after`. Do not retry in a tight loop; that
  extends the limit.
- The daily cost digest (08:00 IST in the ops chat) shows spend by model. A sudden jump means a
  loop or abuse. See [Abuse](#abuse-or-a-runaway-sender).

## Database is down or full

`/readyz` says `database`. Check in the Supabase dashboard (project `anviq-prod`, Mumbai).

- **Connection errors**: confirm `DATABASE_URL` is still correct (a password rotation changes it).
  `fly secrets set DATABASE_URL=… -a anviq-prod`.
- **Disk full**: the largest tables are `turns` and `mirror_clips`. Transcripts older than 90 days
  are removed by the hourly purge; confirm the worker log shows `retention purge:` every hour. If
  it does not, the worker is down: `fly status -a anviq-prod` and restart it
  (`fly machine restart <worker-machine-id> -a anviq-prod`). If the purge ran and the disk is still
  full, raise the plan's disk size. Do not delete rows by hand, because `sessions` and aggregates
  depend on the purge's ordering.
- **Bad migration**: the release command runs `alembic upgrade head` before traffic moves. A failed
  release leaves the old version running. Read the failure with `fly releases -a anviq-prod`.
- **Restore**: Supabase keeps daily backups. A restore replays data that teachers may have already
  asked us to delete. After any restore, re-apply deletions from `deletion_log` (it holds only
  hash prefixes, so match on the `phone_hash` prefix) and tell the incident owner.

## Redis is down

`/readyz` says `redis`, or the webhook returns 503. Inbound messages are refused with 503 so Meta
retries them. Restore Upstash (or the Redis host) and check `REDIS_URL`. Dedupe ids and rate-limit
counters live there, so after a flush a few duplicate deliveries can be processed twice; the cost
is a repeated reply, not data loss.

## API will not start

The app refuses to start when a required secret is missing, by design.

```bash
fly logs -a anviq-prod | head -60
```

Common causes: `FIELD_KEY` or `PHONE_PEPPER` missing or not base64 of 32 bytes (the error names
which); `WA_APP_SECRET` or `WA_VERIFY_TOKEN` unset; a malformed `WEB_ALLOWED_ORIGINS`.

Never start prod without `PHONE_PEPPER`: outside local development a missing key is a hard
failure precisely so a restart cannot silently change every phone hash.

## Rolling back a release

```bash
fly releases -a anviq-prod                       # find the last good version
fly deploy -a anviq-prod --image <previous-image-ref>
```

Migrations are forward-only in practice. If the bad release included a migration, roll the code
back only if the migration was additive; otherwise fix forward.

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

- Issue a code on the running API machine:
  `fly ssh console -a anviq-prod -C "uv run --no-sync python -m app.web.issue_code --turns 20"`.
  The code is printed once and only its hash is stored. It expires after 7 days. It must be issued
  with the same `PHONE_PEPPER` as the API, which the machine already has.
- A visitor whose code does not work gets one message for every cause (wrong, expired, used up).
  Issue a new code rather than trying to recover the old one.
- If browser calls fail with a CORS error, add the page's origin to `WEB_ALLOWED_ORIGINS`
  (JSON list or comma-separated) and restart.
- `could not refund a web turn` means a turn was spent and not given back. It is a one-off; the
  fix is to issue the visitor a fresh code.

## Abuse or a runaway sender

- Per sender: 60 messages an hour, then messages are dropped with a log line and no reply.
- Per demo code: the same 60 an hour, plus the code's own turn budget.
- To block a number entirely, raise it with the incident owner; there is no block list yet.
- Watch the daily cost digest. A day that costs several times the trailing average is the signal.

## Rotating secrets

Rotate any secret that may have been exposed immediately, then write it up in
[incident-response.md](incident-response.md).

| Secret | How | Side effects |
|---|---|---|
| `WA_ACCESS_TOKEN`, `WA_APP_SECRET`, `WA_VERIFY_TOKEN` | Generate in Meta, then `fly secrets set` on both apps | Restart; update the Meta webhook if the verify token changed |
| `SARVAM_API_KEY`, `GOOGLE_SPEECH_API_KEY`, `ANTHROPIC_API_KEY` | New key in the vendor console, `fly secrets set`, then revoke the old key | Restart |
| `SENTRY_DSN`, `OPS_WEBHOOK_URL` | New value from the provider, `fly secrets set`, revoke the old one | Restart. The webhook URL is a credential: anyone with it can post to the ops chat |
| `DATABASE_URL` | Rotate the database password in Supabase, then set it | Restart |
| `REDIS_URL` | Rotate in Upstash, then set it | Restart |
| `FIELD_KEY` | **Needs a scripted re-key.** See below | Do not just change it: stored ciphertext becomes unreadable |
| `PHONE_PEPPER` | **Needs a scripted re-hash.** See below | Invalidates all issued demo codes and changes per-sender rate-limit keys |

Secrets set with `fly secrets set` restart the machines. Do one app at a time and check `/readyz`.

### `FIELD_KEY` and `PHONE_PEPPER` (not yet automated)

Neither key carries a version, so changing the value in place breaks every row that was written
with the old one. There is **no rotation script yet**. Until there is, the safe procedure is a
one-off maintenance task, run during a quiet window with a database snapshot taken first:

1. Take a Supabase backup and note the time.
2. For `FIELD_KEY`: read each `teachers.wa_id_enc` and `mirror_clips.audio_enc`, decrypt with the
   old key, encrypt with the new key, write back in one transaction.
3. For `PHONE_PEPPER`: for each teacher, decrypt `wa_id_enc`, recompute `phone_hash` with the new
   pepper, write back in the same transaction. The WhatsApp id is the phone number, so this is
   possible without asking anyone.
4. Set the new key in Fly secrets immediately after the transaction commits, and restart.
5. Re-issue any outstanding web demo codes.

Building and testing this script is an open item in the [data inventory](data-inventory.md#known-gaps).
A key that is lost, rather than rotated, makes the affected data unrecoverable: store both keys in
the team's secret manager as well as in Fly.

## After any incident

Write down what happened, what you did and what would have caught it sooner. If personal data may
have been exposed, stop and follow [incident-response.md](incident-response.md) first; the
reporting clock starts when you become aware.
