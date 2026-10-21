# Device QA checklist (Joepaul, J6)

Manual smoke test for the two judge-facing UIs on the hardware the judges actually
use: a budget Android (2-3 GB RAM) on throttled 3G. Run before every submission
and before the finale demo. Tick every box; a single failure blocks submission.

## Setup

- [ ] Device: Android 11+, 2-3 GB RAM, Chrome latest. Clear site data first.
- [ ] Network: Chrome DevTools "Slow 3G" or a real 3G SIM. Disable Wi-Fi.
- [ ] Dashboard URL deployed (Vercel) + a valid dashboard token.
- [ ] Web room URL deployed + a demo code with at least 3 turns left.
- [ ] API base reachable over HTTPS (demo VM).

## Web room (`web-room/`)

- [ ] Gate screen renders; code field accepts paste; Enter submits.
- [ ] A 22-char code is accepted; malformed code shows the single refused message.
- [ ] Hold-to-talk: pointerdown starts recording after ~350 ms; visual "recording" state shows.
- [ ] A 3-second voice note uploads as audio/webm (or fallback mime) and gets a reply.
- [ ] Reply text renders; if audio_base64 present, a play button appears and plays inline.
- [ ] "Type instead" path sends text/plain and renders the reply.
- [ ] Saying/typing "bas" (or "stop"/"enough") ends the session and returns to the gate.
- [ ] When turns run out, the single refused message appears; no count is leaked.
- [ ] No transcript or recording persists after refresh (verify via DevTools Application tab).
- [ ] No third-party scripts load (Network tab).
- [ ] All tap targets >= 44 px; usable one-handed in portrait.
- [ ] Total page weight < 200 KB (no frameworks).

## Dashboard (`dashboard/`)

- [ ] Connection card accepts API URL + token; "remember" persists to localStorage.
- [ ] Wrong token shows "Token rejected"; unconfigured feed shows 503 message.
- [ ] Trends grid renders weeks x clusters x moves; suppressed cells show "Suppressed < 20".
- [ ] Move filter and week window change the view without a reload.
- [ ] Empty state (no rows) explains the k>=20 rule instead of showing an empty table.
- [ ] No per-teacher data anywhere (inspect DOM + network).
- [ ] Static export loads from a file:// or any static host without a server.

## Cross-cutting

- [ ] Voice notes play inline (WhatsApp-style) on the device's default player.
- [ ] p95 turn latency <= 20 s on Slow 3G (measure 5 turns).
- [ ] No console errors during a full daily loop.
- [ ] Lighthouse mobile score >= 80 (Performance + Accessibility).

## Sign-off

Tester: __________  Date: __________  Device: __________  Result: PASS / FAIL
Notes:
