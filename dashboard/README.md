# Mentor dashboard

The read side of the bargain in "Mirror, not monitor": mentors, CRPs and DIET see how a
**group** is doing, but there is no view of a single teacher anywhere in this codebase, not
even here. Groups smaller than 20 teachers are dropped in SQL by the `public_trends` view
(see migration `0002_core_schema.py`); this dashboard only draws what that view returned.

## It reads exactly one endpoint

`GET {API}/dashboard/trends`, with `Authorization: Bearer <token>`, answers:

```json
{ "k_threshold": 20, "rows": [
  { "cluster_code": "…", "move_id": 2, "iso_week": "2026-W45",
    "n_teachers": 24, "avg_improvement": 2.1, "avg_sessions": 3.4 } ] }
```

- Cells the view suppressed never appear as rows. The page renders them as
  **"Suppressed · < 20"** so a blank hole is understood, not hidden.
- The token is an anti-scrape gate only. Anonymity does not depend on it; a leaked token
  yields nothing more than the suppressed grid.
- The API answers 503 when the feed is not configured on that deployment (`DASHBOARD_*`
  env not set) and 401 on a wrong token; both have their own message on the page.

## Pages on it

- **Connection card:** API URL + token, stored in `localStorage` only if the device owner
  ticks "remember" (the token is disposable).
- **Trends grid:** weeks × clusters × moves, with a move filter and a week window.
- **Demo mode:** `look at demo data` renders synthetic rows from `lib/synthetic.ts`,
  labelled as demo. It mirrors the view's behaviour, including a deliberately sub-threshold
  cluster that stays invisible, so the suppression story can be shown before real pilot
  data exists.

## Deploy (Vercel)

1. Import the repo; set **Root Directory** to `dashboard/`.
2. Framework preset detects Next.js; `next.config.mjs` uses `output: "export"` so it
   builds to static assets and needs no server functions.
3. No environment variables — connection details are entered by the viewer. Point mentors
   at the deployed URL plus a dashboard token.

Local run: `npm install && npm run dev`, then open `http://localhost:3000`, or npm run
build for the static export in `out/`.

## Not here, on purpose

- Any per-teacher table, name, phone or score. The API role behind this feed
  (`dashboard_ro`) can `select` on `public_trends` and nothing else, so a compromised page
  cannot ask for more.
- Numbers shown to teachers: teachers see 🌱 🌿 🌳 in their own chat, never compared with
  anyone.
