# Incident response (personal data breach)

What to do when teacher data may have been exposed, lost or altered. For outages with no data
exposure, use the [runbook](runbook.md) instead.

This page follows the plan's DPDP mapping (breach intimation to the Data Protection Board and to
affected teachers without delay, with a detailed report within 72 hours). The exact legal wording
of the Rules should be confirmed with counsel before the full pilot; nothing here replaces that.

## Who owns it

| Role | Person | Does |
|---|---|---|
| Incident owner | Marutey | Declares the incident, runs this page, signs off the reports |
| Backup owner | Aadi | Takes over if the owner cannot be reached within 1 hour |
| Grievance contact | **To be filled in before the pilot** (email and phone, as printed in the consent note) | Receives teacher complaints and questions |

Confirm these names with the team. An incident with no named owner is the failure this page exists
to prevent.

## What counts as an incident

Treat any of these as one until shown otherwise:

- A secret that protects teacher data was exposed: `FIELD_KEY`, `PHONE_PEPPER`, `DATABASE_URL`,
  `WA_ACCESS_TOKEN`, `WA_APP_SECRET`, the Fly token, or a vendor API key. Includes a secret pasted
  into a chat, a ticket or a commit.
- Someone outside the team read, copied or changed rows in the database, Redis or backups.
- A reply was sent to the wrong teacher, or one teacher saw another's content.
- The dashboard returned something other than an aggregate for a group of 20 or more.
- Error reports or logs contained a transcript, a phone number or a credential.
- A vendor tells us they had a breach that touched our data.
- A device or account with access (laptop, Fly, Supabase, Meta, GitHub) was lost or taken over.

When unsure, declare it. Closing a false alarm costs an hour. A missed breach costs the clock.

## The clock

The reporting clock starts when the team becomes **aware**, not when the breach began. Write the
time down first.

| By | Do |
|---|---|
| Immediately | Contain (below). Note the awareness time and who noticed |
| Within 1 hour | Owner declared and the backup told. Start the incident log |
| Without delay | Tell the Data Protection Board and each affected teacher (below) |
| Within 72 hours | Send the Board the detailed report |

## 1. Contain

Stop it getting worse before working out how it happened.

1. **Rotate** the exposed secret now ([runbook: rotating secrets](runbook.md#rotating-secrets)).
   Revoke the old value at the vendor, not just in Fly.
2. If a database credential is involved, rotate `DATABASE_URL` first. It also cuts off anyone
   holding the old one.
3. If a WhatsApp token is involved, revoke it in Meta Business Settings.
4. If an account was taken over, remove the member, force a password reset, and revoke sessions
   and personal access tokens.
5. If a code path is leaking, turn it off rather than debug it live: roll back
   ([runbook](runbook.md#rolling-back-a-release)) or take the API down with
   `fly scale count 0 -a anviq-prod`. A short outage is better than a continuing leak.
6. **Do not delete evidence.** No log purges, no force-pushes, no clearing Sentry. Take a database
   snapshot and save the relevant `fly logs` output.

## 2. Work out what was exposed

Use the [data inventory](data-inventory.md). It says exactly what each store holds, so you can
answer from it rather than guess.

Answer, in writing, in the incident log:

- What data: which tables, fields and time range?
- Whose: how many teachers, and which ones? (Match on `phone_hash`; never copy phone numbers into
  the log.)
- Could it be read? Hashes and AES-GCM ciphertext are useless without `PHONE_PEPPER` and
  `FIELD_KEY`. If those keys were **not** exposed, say so; it changes the severity a great deal.
  If either key was exposed, assume the matching field is readable.
- What is scrubbed and what is not: `turns.text_scrubbed` is scrubbed, but `turns.child_name` and
  `turns.criteria_json` are not (see the data inventory's known gaps), so treat those as readable
  content.
- Was a child affected? We do not collect child data on purpose, but a teacher can still say a
  name. If a child's name reached an exposed field, record that, because the Act is stricter there.

## 3. Tell the Data Protection Board

Without delay after awareness, then the detailed report within 72 hours. Include:

- What happened, and when it started and ended (if known).
- The data and the number of teachers affected, from step 2.
- The likely consequences for them.
- What we did to contain it and what we are doing to stop it recurring.
- Who to contact (the incident owner).

Send through the channel the Board prescribes. **Confirm the current channel and form with counsel
before the pilot starts**, so it is not being looked up during an incident. Keep the sent report
and the acknowledgement in the incident log.

## 4. Tell the affected teachers

Without delay, in the teacher's own language (Hindi or English, per `teachers.lang`), through
WhatsApp, in plain words. Say:

- What happened and what data was involved.
- What it could mean for them, honestly, without alarm.
- What we have done.
- What they can do (for example, delete their data by saying "मेरा डेटा मिटाओ").
- Who to contact.

Draft the message in both languages once, now, and keep it with this page (**to do**), so the
owner edits rather than writes from scratch. Send it from the production number. Do not send it as
a bulk template without a check that it is correct. Use the `teachers` table only to pick
recipients; do not read content.

If the exposure was limited to the staging environment and no real teacher data was involved, no
teacher notice is needed. Record why.

## 5. Recover

- Restore from backup only if data was lost or altered. A restore replays data teachers may have
  deleted: re-apply `deletion_log` afterwards ([runbook](runbook.md#database-is-down-or-full)).
- Re-key if `FIELD_KEY` or `PHONE_PEPPER` was exposed. This is **not yet scripted**; see the
  runbook and the data inventory's known gaps. Until it is, the fix is a maintenance window with a
  snapshot taken first.
- Re-issue web demo codes if `PHONE_PEPPER` changed.
- Add a test or a check that would have caught it.

## 6. Afterwards

Within a week, write a short review with no blame in it:

- Timeline, with times in IST.
- Root cause.
- What worked and what slowed us down.
- Changes made, and who owns each.

File it next to the incident log. Update the [data inventory](data-inventory.md), the
[runbook](runbook.md) and the [DPIA](DPIA.md) if the incident showed something they got wrong.

## Incident log template

Copy this into a private note when you declare an incident. Keep it out of the repository.

```text
Incident:           <short name>
Declared:           <date, time IST>   Aware since: <date, time IST>
Owner / backup:     <name> / <name>
What happened:      <facts only>
Data involved:      <tables, fields, time range>
Teachers affected:  <count; ids by phone_hash prefix only>
Keys exposed?:      FIELD_KEY <y/n>   PHONE_PEPPER <y/n>
Contained at:       <time>   How: <steps>
Board told:         <time>   Detailed report sent: <time>
Teachers told:      <time>   Language(s): <hi/en>
Open actions:       <owner, due>
```
