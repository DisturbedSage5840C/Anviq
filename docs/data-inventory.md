# Data inventory

What Anviq holds about a teacher, where, for how long and who can see it. This is the source for
the consent note and the DPIA. If the code and this page disagree, the code is wrong or this page
is out of date: fix whichever it is in the same change.

Last reviewed against the schema at migration `0006`.

## What we hold

| Data | Stored? | Where | Retention | Who can see it |
|---|---|---|---|---|
| Phone number | A keyed hash for lookup, plus the WhatsApp id encrypted so we can reply | Postgres (Mumbai) | Until the teacher deletes | Backend only |
| Raw voice notes | **No**, except opt-in mirror clips below. Otherwise decoded in memory and dropped | Nowhere (Meta keeps its own copy under its policy) | n/a | Nobody |
| Transcripts, scrubbed | Only the teacher's scored practice questions, with the coach's judgment | Postgres `turns` | **90 days rolling** | Backend only; the teacher on request |
| Rubric results | Yes | Postgres `turns`, `move_progress` | Until the teacher deletes | The teacher only |
| Session summaries | Yes, derived; a practice left open for a day is closed, not deleted | Postgres `sessions` | Removed with the last transcript of the session | Backend only |
| Mirror voice clips | Opt-in only, encrypted | Postgres `mirror_clips` | 30 days from capture (`expires_at`); only the first and latest practice recording are kept; deleted at once on 'stop saving my recordings', withdrawal or erasure | The teacher only |
| Consent records | Yes: version, text hash, grant and revoke time | Postgres `consents` | Until the teacher deletes | Backend only |
| Reminder preference | Opt-in flag and time of day | Postgres `teachers` | Until the teacher deletes | Backend only |
| Webhook dedupe ids | Yes | Redis | 7 days (TTL) | Backend only |
| Per-sender rate-limit counters | Yes, keyed by an opaque hash | Redis | 1 hour window | Backend only |
| Daily model-step counters | Yes, keyed by an opaque hash and the IST date | Redis | 2 days (TTL) | Backend only |
| Deletion proof | First 8 hex characters of the phone hash and a timestamp | Postgres `deletion_log` | Indefinite; holds no personal data | Backend only |
| Cost telemetry | Model, token counts, seconds or characters, estimated cost. **No content** | Postgres `llm_usage`, `speech_usage` | Indefinite | Backend only |
| Aggregates | Anonymous, only for groups of 20 or more teachers | View `public_trends` | Indefinite | Mentors and DIET, via the dashboard |
| Child data | **Never collected.** Teachers are told not to name pupils and a scrubber replaces common names | n/a | n/a | n/a |
| Web-room demo codes | Only an HMAC of the code; never the code | Postgres `demo_codes` | 7 days, then purged | Backend only |
| Error reports | Stack traces and ids, scrubbed. No bodies, headers with credentials, user block or local variables | Sentry (only if `SENTRY_DSN` is set) | Per Sentry plan | Engineering |

## Fields that need special care

| Field | Protection |
|---|---|
| `teachers.phone_hash` | HMAC-SHA256 keyed with `PHONE_PEPPER`. The raw number is never an index. |
| `teachers.wa_id_enc` | AES-256-GCM with `FIELD_KEY`, random 96-bit nonce per value. The one reversible field, kept only because a reply needs the id. |
| `mirror_clips.audio_enc` | Encrypted the same way. Written only after an explicit opt-in ('save my recordings'). |
| `turns.text_scrubbed` | Passed through `guardrails.pii.scrub` before it is written. |
| `turns.child_name`, `turns.malrule_id`, `turns.criteria_json` | Scrubbed like the words: `record_turn` passes the child name and misconception id through `guardrails.pii.scrub`, and keeps only the rubric ids' true/false values. The writer already passes fixed values; this enforces it. |

## Who is allowed to read what (database roles)

| Role | Access |
|---|---|
| `app_rw` | Select, insert, update, delete on the application tables. Used by the API and the worker. |
| `dashboard_ro` | Select on the `public_trends` view and **nothing else**. |
| anonymous | No access. Row level security is on for every table. |

`public_trends` is a `security_barrier` view that only returns a group of 20 or more teachers,
floors the teacher count to a multiple of 5 and rounds averages to one decimal. This makes
differencing harder. It is not differential privacy; see the [DPIA](DPIA.md).

## What leaves our systems

| Recipient | What they get | Location | Notes |
|---|---|---|---|
| Meta (WhatsApp Cloud API) | Messages and voice notes the teacher sends and the replies we send | Per Meta | Meta keeps its own copy under the WhatsApp policy; the consent note says so |
| Google Cloud Speech | Teacher audio for speech-to-text, reply text for text-to-speech (`STT_PROVIDER` and `TTS_PROVIDER` are `google` on the demo) | Per Google | Record the data processing terms; confirm no retention or training |
| Anthropic | Scrubbed transcript text and prompts | US | API data is not used for training under the commercial terms. Production path is an India-region Bedrock profile |
| Sentry | Scrubbed error events | Per Sentry | Off unless `SENTRY_DSN` is set |
| Ops webhook | The daily cost digest: counts and rupee totals, no content | Per the chat provider | `OPS_WEBHOOK_URL` is itself a credential |

## Rights and how they are served

| Right | How |
|---|---|
| Access | The teacher sends "send me my data". The reply is a text summary: language, grade, consents, reminder setting, reminder time and last reminder day, the number of practice sessions and scored questions, the saved plan topic, and whether a practice is in progress. The teacher's words and the saved progress are not repeated. |
| Erasure | The teacher asks to delete and confirms. The teacher row is deleted; transcripts, sessions, progress, consents and clips are removed by cascade. A `deletion_log` row keeps only the hash prefix. Backups age out within 7 days. |
| Withdraw consent | The teacher says so at any time; the consent row is marked revoked. |
| Correction | There is no self-service correction command yet. A teacher who wants a detail changed asks through the grievance contact, or deletes and starts again. |
| Grievance | The contact in the consent note and on the privacy page. |

## Known gaps

These are tracked and not hidden. Each needs a decision or a change before the full pilot.

1. The web room records consent under channel `whatsapp`, which blurs the record for audit.
2. Web-room teacher rows are not purged when their demo code expires.
3. `FIELD_KEY` and `PHONE_PEPPER` have no key version, so rotating either needs a scripted re-key
   (see the [runbook](runbook.md)).
4. The `demo_codes` grants are broader than the table needs.
5. Correction (DPDP S.12) has no in-chat command; see the rights table.
