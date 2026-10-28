# Data protection impact assessment

A plain-language assessment of the privacy risk Anviq creates for teachers, what we do about it and
what risk is left. It is a working document for the team and for the people who will review the
pilot, not legal advice. Have counsel review it before the full pilot.

It rests on the [data inventory](data-inventory.md), which is the source for what is stored. If the
two disagree, fix whichever is wrong in the same change.

Status: draft for the mini-pilot. Reviewed against schema migration `0006`.

## 1. What Anviq is

A WhatsApp voice coach for teachers of Grades 1 to 3. A teacher talks to Anviq, practises a
teaching move with AI-played children, and gets private feedback. A browser demo ("web room") offers
the same for people who are not on the WhatsApp test list.

Anviq is for **practice and reflection**, never for evaluating a teacher. No score leaves the
teacher's chat.

## 2. Who is affected

| Group | How |
|---|---|
| Teachers (Gr 1 to 3, Hindi and English) | Their voice, words, phone number and practice progress are processed |
| Children in their classes | Not intended to be processed at all. A teacher may still say a name |
| Mentors, CRPs and DIET staff | See only anonymous trends. Nothing about an individual |
| Web-room visitors | A demo code, and what they say or type in that session |

Teachers are adults using the service by choice. They are not employees of Anviq. Some work under
state education departments, so a power imbalance with their institution is plausible even though
Anviq is not run by it. This is the main reason for the "mirror, not monitor" rule below.

## 3. Purposes, and nothing else

1. Coaching rehearsal: practise, get feedback, track personal progress.
2. Ask Anviq: answer a question using the NISHTHA and NIPUN material, with citations.
3. Anonymous programme trends for groups of 20 or more teachers.

Data is not used for advertising, profiling, selling, or training any model. Anviq does not
fine-tune on teacher data, and the Anthropic API does not train on API data under the commercial
terms. Google Cloud's speech terms are to be recorded (see the actions below).

## 4. Why each piece of data is needed

| Data | Needed because | Smaller alternative considered |
|---|---|---|
| Phone number (hash and encrypted id) | To recognise the teacher and send a reply on WhatsApp | A hash alone cannot reply, so the reversible id is kept, encrypted |
| Scrubbed transcripts, 90 days | To give feedback, resume a session, show progress | Shorter retention; 90 days covers a 14 day cycle plus review |
| Rubric results | To show the teacher her own growth | None; this is the product |
| Mirror voice clips | Day 14 "hear how you've grown" (the Day-14 mirror plays the first and latest back to the teacher in their own chat) | Opt-in only ('save my recordings'), encrypted, only the first and latest practice recording kept, deleted after 30 days or when the teacher opts out, withdraws or erases |
| Consent records | To prove what was agreed and when | None; required |
| Reminder preference | To send a reminder the teacher asked for | Off by default |
| Raw audio | Not kept, except the opt-in mirror clips above. Otherwise decoded in memory and dropped | n/a |
| Child data | Not collected | n/a |

## 5. Risks and how we reduce them

Rated before and after our safeguards: Low, Medium or High.

| # | Risk | Before | Safeguards | After |
|---|---|---|---|---|
| 1 | A phone number is exposed from the database | High | Only a keyed HMAC is indexed. The reversible id is AES-256-GCM encrypted with a key held outside the database. Row level security on every table | Low if keys stay secret |
| 2 | Teacher speech or words leak through logs or error reports | High | Structured logs hold ids and latency, not content. Sentry is off unless configured, has SDK PII switches off, and rebuilds every event through the scrubber (drops request bodies, local variables and the user block; reduces HTTP breadcrumb URLs to the host; replaces any 10 to 15 digit run) | Low |
| 3 | A child is identifiable from something a teacher says | Medium | Teachers are told not to name children. The scrubber replaces common names and phone-like strings before storage. Anviq's own AI children are allow-listed | Medium, see residual risks |
| 4 | Institutions use Anviq to monitor individual teachers | High | No per-teacher view exists anywhere in the code. Dashboard reads one view only, with k of at least 20 enforced in the database, counts floored to a multiple of 5 and averages rounded | Medium, see residual risks |
| 5 | A teacher cannot leave or have data removed | Medium | Delete by message with a confirmation step; cascade removes all personal rows; proof kept as an 8 character hash prefix. Withdraw consent any time | Low |
| 6 | Data sent to processors is misused or retained | Medium | Audio is not stored by us unless the teacher opts in to mirror clips. Anthropic API data is not used for training. Google Cloud speech terms are to be recorded | Medium until confirmations are filed |
| 7 | Data leaves India | Medium | LLM calls go to the US under the Anthropic API. Production path is an India-region Bedrock profile. Speech goes to Google Cloud and is not pinned to India. Database is in Mumbai | Medium until Bedrock is in use |
| 8 | A demo code is guessed or shared | Medium | 128-bit codes, stored only as an HMAC, expiring after 7 days, with an atomic turn budget and a per-code rate limit. One refusal message for every cause | Low |
| 9 | A recycled or taken-over phone number reaches the previous holder's account | Medium | The account is keyed on the phone number, so whoever holds the number is treated as the teacher. Mitigated only by WhatsApp's own account verification and by the teacher's ability to delete. Anviq has no second factor | Medium, see residual risks |
| 10 | A breach goes unreported or unhandled | High | [Incident response](incident-response.md) with a named owner, a contain-first checklist and the reporting clock | Low |
| 11 | A secret is lost or has to change | Medium | Rotation steps in the [runbook](runbook.md). Re-keying `FIELD_KEY` and `PHONE_PEPPER` is not yet scripted | Medium until scripted |
| 12 | Consent is unclear or hard to prove | Medium | Hindi and English notice, explicit "yes" required, versioned consent row with the text hash, revocation recorded | Low |

## 6. Residual risks we are accepting, and why

### 6.1 Aggregates are anonymised, not differentially private

The `public_trends` view only returns groups of at least 20 teachers, floors the teacher count to a
multiple of 5 and rounds averages to one decimal. That blocks reading one teacher from a small
group and makes subtracting two overlapping reports less precise.

It is **not** differential privacy. An attacker who can see how the group changes when a single
known teacher joins or leaves, and who can see repeated reports over time, may still infer
something about that teacher. We accept this for the pilot because the dashboard shows coarse
programme trends, not sensitive attributes, and nothing in it is a score. Before wider use, add
noise or cap how often the view changes, and review which fields it exposes.

### 6.2 The scrubber is a filter, not a guarantee

Name detection works from a list of common names. An uncommon name, a nickname or a name inside a
longer sentence can pass through. `turns.child_name`, `turns.malrule_id` and `turns.criteria_json`
are scrubbed on write too, though they only ever hold fixed values. Mitigations: teachers are told
not to name children, transcripts expire after 90 days, and the data is visible only to the
backend.

### 6.3 Cross-border processing

Teacher words reach Anthropic in the US for the coach and planner. They are scrubbed first, except
the turn in flight, which needs the child's name to route. Production moves to an India-region
Bedrock profile. Until then the consent note says plainly that the text is processed outside India.

### 6.4 Meta keeps its own copy

WhatsApp messages and voice notes pass through Meta and are kept under Meta's policy. We cannot
delete Meta's copy. The consent note says so.

### 6.5 Key handling

`FIELD_KEY` and `PHONE_PEPPER` have no version, so rotation needs a scripted re-key that does not
exist yet. A leaked key is the largest single risk in the system. It is handled by keeping keys only
in the secret managers, never in the repository (gitleaks runs before every commit and in CI), and by
the incident process.

### 6.6 The phone number is the identity

Anviq trusts that the WhatsApp number belongs to the teacher. If a number is recycled by the
operator or a SIM is taken over, the new holder sees the previous holder's progress and transcripts
(scrubbed, within 90 days). WhatsApp re-verifies a number when it moves to a new device, which is
the main protection. We accept this for the pilot because the content is practice feedback, not
sensitive records. Before wider use, consider a periodic "is this still you?" check or a short
PIN for deletion and export.

### 6.7 Other known gaps

Listed with owners in the data inventory: web-room consent is recorded under channel `whatsapp`;
expired web teacher rows are not purged; `demo_codes` grants
are broader than needed; there is no in-chat command for correcting details.

## 7. Processors and recipients

| Processor | Role | Contract or terms | Status |
|---|---|---|---|
| Meta | WhatsApp delivery | WhatsApp Business terms | Accepted by use; disclosed to teachers |
| Anthropic | Coach, planner and children (US) | Commercial API terms; no training on API data | Recorded; production path is Bedrock India |
| Google | Speech to text and text to speech (Cloud Speech-to-Text and Text-to-Speech), used for both on the demo | Cloud terms | **Record the data processing terms; confirm no retention or training** |
| Google Cloud | One VM in Mumbai (asia-south1, trial credit) running the API, worker, Postgres with pgvector and Redis | Standard terms | **File the DPA** |
| Vercel | Dashboard hosting | Standard terms | The dashboard reads aggregates only |
| Sentry | Scrubbed error events | Standard terms | Off unless `SENTRY_DSN` is set |

Keep the signed or accepted terms for each in one folder, with the date.

## 8. Rights

Teachers can ask for access, deletion and withdrawal of consent by messaging Anviq; the data
inventory's rights table says how each is served. Correction has no self-service command yet: until
there is one, it goes through the grievance contact, or the teacher deletes and starts again.
The grievance contact is printed in the consent note and on the privacy page.

## 9. Decisions before the full pilot

These are what would change the risk ratings above. Each needs an owner and a date.

1. Record Google Cloud's data processing terms (accepted in the console) for the VM and for speech, and confirm speech inputs are not retained or used for training.
2. Have the changed consent note (v3, opt-in recordings) reviewed by the content owner.
3. Script the `FIELD_KEY` and `PHONE_PEPPER` re-key and test it on a copy of the database.
4. Fill in the grievance contact and the Board reporting channel ([incident response](incident-response.md)).
5. Have counsel read this page, the consent note and the incident process.
6. Decide whether the dashboard needs noise before it is shown beyond the pilot group.
7. Move the LLM to the India-region Bedrock profile, or record why not.
8. Decide whether deletion and export need more than possession of the phone number.

## 10. Review

Review this assessment when any of these happens: a new data field, a new processor, a new
purpose, a change to what the dashboard shows, an incident, or before each pilot phase. Record the
date and what changed.

| Date | By | Change |
|---|---|---|
| 2026-10-18 | Marutey | First draft |
