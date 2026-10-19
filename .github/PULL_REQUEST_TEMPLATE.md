## What and why

<!-- One or two sentences. Link the plan section or issue if there is one. -->

## How it was tested

<!-- Tests added or changed, and what you ran by hand. Tests come first for router, guardrails,
privacy and the k-anonymity view. -->

## Privacy checklist

Tick every line or write "n/a" and why. A reviewer will not merge with a blank line.

- [ ] No teacher data in logs, error reports, fixtures or test output (phone numbers, names, transcripts, audio)
- [ ] Anything new that stores a teacher's data is listed in `docs/data-inventory.md` with its retention
- [ ] A new table keyed by `teacher_id` is erased by "delete my data" (`tests/db/test_erase_coverage.py` stays green)
- [ ] Free text from a teacher is scrubbed before it is stored or sent to a model
- [ ] The dashboard still reads only `public_trends` (k >= 20); no new path to a single teacher's row
- [ ] No secret, key or token in the diff; new settings are in `.env.example` as names only
- [ ] Anything sent to a vendor (speech, model, embeddings) is named in the PR and was already allowed

## Checks

- [ ] `ruff check`, `ruff format --check`, `mypy app` and `pytest` are green
- [ ] Coverage of `app/core`, `app/privacy` and `app/guardrails` is still at least 80%
- [ ] Docs updated if behaviour, environments or operations changed
