# Free always-on demo deployment

For the hackathon: judges try Anviq after we submit, so it has to stay up without anyone's laptop,
cost nothing, and feel fast. This runs the whole backend on one free VM with automatic HTTPS.
This is the only deployment the repo ships. A managed, multi-environment setup is a decision for
after the hackathon.

What you get: Caddy (HTTPS) → API, plus the worker, Postgres+pgvector and Redis, all from
`infra/docker-compose.demo.yml`. Only ports 80 and 443 are open.

## What you need

| Item | Cost | Notes |
|---|---|---|
| Anthropic API key | pay-as-you-go | Already have it. Demo codes cap spend (below) |
| Sarvam API key | starter credits | Hindi speech. Required: the app refuses to start in this mode without it |
| Oracle Cloud account | free | Always Free VM in the Mumbai region. Needs a card for sign-up only |
| DuckDNS subdomain | free | Stable HTTPS name, e.g. `anviq.duckdns.org` |
| Meta developer app | free | Optional now. The test number reaches at most 5 whitelisted phones, so judges use the web room |

Limits and sign-up steps for Oracle and DuckDNS are written from memory; check their pages.

## 1. Create the VM

1. In Oracle Cloud pick the **Mumbai (ap-mumbai-1)** home region at sign-up (it cannot be changed).
2. Create a compute instance on an Always Free shape (Ampere A1 if capacity exists, otherwise the AMD micro).
   Ubuntu 24.04. Add your SSH key.
3. In the instance's subnet security list, allow inbound TCP **80** and **443** from `0.0.0.0/0`.
4. On the VM, also open the host firewall (Oracle's Ubuntu images block these by default):
   ```
   sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
5. Install Docker: follow https://docs.docker.com/engine/install/ubuntu/ (includes the compose plugin).

## 2. Point a name at it

Create a subdomain at https://www.duckdns.org and set its IP to the VM's public IP.
Caddy needs this name to fetch a free certificate.

## 3. Configure

```
git clone https://github.com/DisturbedSage5840C/Anviq.git && cd Anviq
cp infra/demo.env.example infra/demo.env
```

Fill in `infra/demo.env`:

- `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`: `openssl rand -hex 24` each (hex keeps them URL-safe).
- `FIELD_KEY`, `PHONE_PEPPER`: `openssl rand -base64 32` each. **Back these up.** Losing `FIELD_KEY`
  makes stored data unreadable; changing `PHONE_PEPPER` makes every teacher look new.
- `SITE_ADDRESS`: your DuckDNS name, e.g. `anviq.duckdns.org`.
- `ANTHROPIC_API_KEY`, `SARVAM_API_KEY`: your keys.
- `WA_VERIFY_TOKEN`: any string you invent. `WA_APP_SECRET`: the Meta app secret, or any placeholder until the Meta app exists.
- `WEB_ALLOWED_ORIGINS`: the web room's URL once it is hosted.

`infra/demo.env` is gitignored. Never commit it or paste it into chat.

## 4. Start

```
docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml up -d --build
```

The first run builds the image, runs migrations, gives the `app_rw` database role its password,
then starts the API, worker and Caddy. Check it:

```
curl https://anviq.duckdns.org/healthz   # {"status":"ok"}
curl https://anviq.duckdns.org/readyz    # {"status":"ready"}
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

## Day to day

- Logs: `docker compose --env-file infra/demo.env -f infra/docker-compose.demo.yml logs -f api worker`
- Update: `git pull`, then rerun the `up -d --build` command.
- Stop: same command with `down` (add `-v` only if you want to delete all data).

## If Oracle is not available

Use Render or Koyeb for the API, Neon for Postgres (supports pgvector) and Upstash for Redis.
Free web services there sleep after idle time, so the first request after a pause is slow, and the
worker may need its own service. Prefer the VM when you can get one.
