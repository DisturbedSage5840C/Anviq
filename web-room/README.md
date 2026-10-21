# Web rehearsal room

A browser demo of the coach for judges and teachers who are not on the WhatsApp test
list ([§4.12 of the plan](../docs/architecture.md)). Hold the button, speak, get the reply
spoken or written back. The same brain and the same privacy rules as WhatsApp run behind
`POST /web/turn`.

No build step, no framework, no dependencies: three files plus a README. Works on budget
Android Chrome; recording falls back through `audio/webm` → `audio/ogg` → `audio/mp4` →
`audio/wav`, all shapes the API accepts.

## How a judge uses it

1. The team issues a demo code and shares one link:
   `python -m app.web.issue_code --turns N` inside the demo VM container prints the code.
2. The judge opens this page and pastes the 22-character code. It is checked against the
   recorded hash; codes expire after 7 days, and every turn shown must be claimed first.
3. Hold **दबाकर बोलिए** to record, or open the "type instead" section. Saying **"बस"**
   closes the session.
4. When the turns run out the API refuses with one message, the same for a wrong, expired
   or used-up code. No count is leaked.

Nothing about the visit is stored beyond what the turn itself needs: no transcript in
`localStorage`, no recordings on disk, no third-party scripts.

## Point it at an API

`config.js` sets `window.ANVIQ_API_BASE`. Leave it empty for "same area as the page"; set
it to the public API URL of the demo stack (`https://…/duckdns`-style) otherwise. A `?api=`
query parameter overrides both for a single visit, which is how UI work is tried against a
local API (`?api=http://localhost:8080`).

The API must list the page's origin in `WEB_ALLOWED_ORIGINS`; with no entry the API
answers without CORS headers and the browser blocks the call.

## Deploy

Any static host works. Pick one:

- **Vercel / Netlify:** import this folder, "other" project type. Set the root directory to
  `web-room/`. No environment variables needed.
- **GitHub Pages:** serve from the branch; the API base must be set in `config.js` because
  the origin stays the same while the API does not.
- **Served by the API itself:** drop the files in the container if ever useful (the API is
  hosted next to them on the demo VM anyway).

## Files

| File | Job |
|---|---|
| `index.html` | Structure: gate, transcript, hold-to-talk button, privacy note |
| `style.css` | Look. Large touch targets; works without a design system |
| `app.js` | Recording, posting, playback, error mapping. Nothing persisted |
| `config.js` | API base for the deployment |
