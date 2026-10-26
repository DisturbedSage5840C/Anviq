# Always-on demo deployment (Google Cloud trial)

For the hackathon: judges try Anviq after we submit, so it has to stay up without anyone's laptop
and feel fast. This runs the whole backend on one VM in Mumbai with automatic HTTPS, paid for by the
Google Cloud free-trial credit. This is the only deployment the repo ships. A managed,
multi-environment setup is a decision for after the hackathon.

What you get: Caddy (HTTPS) → API, plus the worker, Postgres+pgvector and Redis, all from
`infra/docker-compose.demo.yml`. Only ports 80 and 443 are open (plus SSH for you).

## What you need

| Item | Cost | Notes |
|---|---|---|
| Anthropic API key | pay-as-you-go | Already have it. Demo codes cap spend (below) |
| Google Cloud free trial | free credit | 90 days and a fixed credit (₹28,797 on our account). Needs a card for sign-up. A trial account is never charged unless you click Upgrade. It also pays for speech (below) |
| Google speech API key | from the trial credit | Hindi and English speech (Speech-to-Text and Text-to-Speech). Required: the app refuses to start without it. Create it in the console under APIs & Services, Credentials, restricted to those two APIs |
| `sslip.io` name | free | A hostname that resolves to the VM's IP, e.g. `35-200-176-62.sslip.io`. No sign-up |
| Meta developer app | free | Optional now. The test number reaches at most 5 whitelisted phones, so judges use the web room |

The VM (`e2-medium`, 2 vCPU, 4 GB, Mumbai) costs about ₹2,500 a month, so the trial credit covers the
whole 90 days with room to spare.

## 1. Create the VM

With the `gcloud` CLI signed in (`gcloud auth login`) and the project selected:

```
gcloud services enable compute.googleapis.com
gcloud compute addresses create anviq-ip --region asia-south1
gcloud compute firewall-rules create anviq-allow-web --network default \
  --allow tcp:80,tcp:443 --target-tags anviq-web
gcloud compute instances create anviq-demo --zone asia-south1-a --machine-type e2-medium \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 30GB --boot-disk-type pd-balanced --address anviq-ip --tags anviq-web \
  --metadata startup-script='#!/bin/bash
apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 git && systemctl enable --now docker'
```

The reserved address is free while a VM uses it. The startup script installs Docker on first boot
(about two minutes). Google's Ubuntu images need no host-firewall change.

## 2. Point a name at it

`sslip.io` answers for any hostname that spells out an IP with dashes, so `35-200-176-62.sslip.io`
resolves to `35.200.176.62` with nothing to sign up for. Caddy needs the name to fetch a free
certificate. If you later buy a domain, point an A record at the reserved address and change
`SITE_ADDRESS`.

## 3. Configure

On the VM (`gcloud compute ssh anviq-demo --zone asia-south1-a`):

```
git clone https://github.com/DisturbedSage5840C/Anviq.git && cd Anviq
cp infra/demo.env.example infra/demo.env
```

Fill in `infra/demo.env`:

- `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`: `openssl rand -hex 24` each (hex keeps them URL-safe).
- `FIELD_KEY`, `PHONE_PEPPER`: `openssl rand -base64 32` each. **Back these up.** Losing `FIELD_KEY`
  makes stored data unreadable; changing `PHONE_PEPPER` makes every teacher look new.
- `SITE_ADDRESS`: the `sslip.io` name from step 2.
- `ANTHROPIC_API_KEY`, `GOOGLE_SPEECH_API_KEY`: your keys.
- `STT_PROVIDER`, `TTS_PROVIDER`: both `google` in the template. Use one provider everywhere; the
  voices are the Google Neural2 ones (`hi-IN-Neural2-A/B`, `en-IN-Neural2-A/B`). Listen to a sample
  before a demo. `sarvam` still works if you set both back and add `SARVAM_API_KEY`, but its starter
  credits are small.
- `WA_VERIFY_TOKEN`: any string you invent. `WA_APP_SECRET`: the Meta app secret, or any placeholder until the Meta app exists.
- `WEB_ALLOWED_ORIGINS`: leave empty. Caddy serves the web room at `/room/` on the same origin as the API, so no CORS entry is needed; set it only if you host the room somewhere else.

`infra/demo.env` is gitignored. Never commit it or paste it into chat. To reuse a file you already
filled in on your laptop, copy it with `gcloud compute scp` and `chmod 600` it on the VM.

## 4. Start

```
docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml up -d --build
```

Use `sudo` in front if your user is not in the `docker` group. The first run builds the image, runs
migrations, gives the `app_rw` database role its password, then starts the API, worker and Caddy.
Check it:

```
curl https://35-200-176-62.sslip.io/healthz   # {"status":"ok"}
curl https://35-200-176-62.sslip.io/readyz    # {"status":"ready"}
```

Everything restarts by itself after a VM reboot (`restart: unless-stopped`).

## 5. Give judges access

Issue a few demo codes, each with a small turn cap so spend stays bounded:

```
docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml \
  run --rm api uv run --no-sync python -m app.web.issue_code --turns 30
```

The code is printed once; only its hash is stored; it expires in 7 days. Put the codes in the
submission form, not in the repo.

`DEMO_CYCLE_MINUTES=5` (default in the template) makes the 14-day mirror cycle last 5 minutes so a
judge can see Day 1 to Day 14 in one sitting.

## 6. Optional: WhatsApp on a spare SIM (Evolution)

Use this only when the official WhatsApp route is blocked. It links a real WhatsApp account to the
server, which WhatsApp's terms do not allow, so the number can be banned. Use a throwaway SIM, keep
the volume low, and never use it for real teachers. Reminders are off on this channel because it
cannot send templates.

1. Put the six lines from the Evolution block of `infra/demo.env.example` into `infra/demo.env`, with
   `WHATSAPP_PROVIDER=evolution`. Generate each secret with `openssl rand -hex 24`.
2. Start the stack with the extra profile (the same command as step 4, plus `--profile evolution`):

   ```
   docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml \
     --profile evolution up -d --build
   ```

3. Create the instance and register the webhook, then ask for a pairing code for the SIM's number
   (country code first, no plus sign):

   ```
   set -a; . infra/demo.env; set +a
   python3 infra/demo/evolution_setup.py setup
   python3 infra/demo/evolution_setup.py pair 91XXXXXXXXXX
   ```

4. On the phone that holds the SIM: WhatsApp > Settings > Linked devices > Link a device > Link with
   phone number instead, then type the code. Check it with `python3 infra/demo/evolution_setup.py
   status`; `open` means paired.

The pairing can drop (the phone offline for days, WhatsApp logging the device out). Run `status` the
day before the demo and on demo day, and run `pair` again if it says anything but `open`. Keep a
screen recording of a full conversation and the browser web room as fallbacks.

## Day to day

- Logs: `docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml logs -f api worker`
- Update: `git pull`, then rerun the `up -d --build` command.
- Stop: same command with `down` (add `-v` only if you want to delete all data).

## Credits that can run out before the judges look

- **Google speech** is billed to the Google Cloud trial credit, so there is nothing separate to top
  up. As an estimate (check Google's current price list), Neural2 voices cost about US$16 per million
  spoken characters, so one realistic teacher-day (about 3,000 characters) is a few US cents, and
  transcription is a small extra. The trial credit and its end date are on the console's billing page.
  If speech ever fails, the app does not: it sends the text reply without the voice note (covered by
  `test_a_text_reply_survives_a_text_to_speech_failure`).
- **Anthropic** hackathon credits (US$500 per team, shared by every teammate using the one key) are
  valid until **20 November 2026**, two days after the Grand Finale, and are not refunded. Keep enough
  for evaluators and the demo, and keep the key on the server only. The organisers are told at 80%
  usage.
- A model can be suspended for the organisation for a while (the API answers 403 `permission_error`,
  "model suspended until <time>"). Turns that need that model fail until the time passes. If it
  happens near a demo, ask the organisers, and as a stopgap point `MODEL_SMART` at another model
  in `infra/demo.env` and rerun `up -d api worker`.

## When the trial ends

The trial stops at 90 days or when the credit is used, whichever is first (check the date on the
console's billing page). Google then stops the VM; it does not charge the card unless you upgrade.
Before then, either upgrade the account (billing starts, about ₹2,500 a month for this VM) or move
the stack to another host. To move it, take a backup (`docs/runbook.md`), copy `infra/demo.env`
including the same `FIELD_KEY` and `PHONE_PEPPER`, and restore. Delete the VM and the reserved
address when you are done with them, because a reserved address that no VM uses is billed:

```
gcloud compute instances delete anviq-demo --zone asia-south1-a
gcloud compute addresses delete anviq-ip --region asia-south1
```

Other hosts that work the same way: any Ubuntu VM with Docker. Free web-service hosts (Render, Koyeb)
sleep after idle time and have no free background worker, so they are not a fit for the WhatsApp
worker without code changes.
