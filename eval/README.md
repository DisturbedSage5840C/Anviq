# Evaluation harness

Checks the slide-9 targets (plan section 8). The code lives in `backend/app/evaluation/` so it shares the product's guardrails and runs from `backend/`:

```sh
cd backend
uv run python -m app.evaluation.character               # AI child keeps its misconception (3,600 turns)
uv run python -m app.evaluation.coach_kappa --from-rubrics   # coach vs rubric examples (smoke set)
uv run python -m app.evaluation.coach_kappa             # coach vs the human gold set
uv run python -m app.evaluation.citations               # Ask Anviq citations and refusals
uv run python -m app.evaluation.latency_cost --days 7   # model latency and $/teacher-day from usage tables
uv run python -m app.evaluation.assumed_day            # prices one assumed teacher-day (no model calls)
uv run python -m app.evaluation.kappa_compare --sheet <filled csv>   # second labeller vs gold (no model calls)
uv run python -m app.evaluation.report                  # writes eval/report.md
```

Each run writes `eval/results/<name>.json`. If a result is missing, the report says "not run" and never counts it as a pass. [`NOTES.md`](NOTES.md) explains what the latest numbers mean and which are not yet valid measurements. Add `--offline` to `character` or `coach_kappa` to run without a key, using a scripted model. That only checks the harness, and the report labels it as such.

All runs except `--offline` need `ANTHROPIC_API_KEY` in `backend/.env`. `citations` also needs the corpus ingested (`uv sync --group ingest`, then `uv run python -m app.core.ask.ingest ../content/corpus/manifest.csv`). The two PDFs are not in git. Download the English and Hindi "Course Book" links from the NISHTHA FLN section of <https://ciet.ncert.gov.in/nishtha> into `content/corpus/`, under the file names in `manifest.csv`.

**Cost.** A full `character` run is 3,600 Haiku calls, plus one regeneration per failure. `--problems 5` gives a 720-turn run for prompt iteration. The runs use ordinary concurrent calls, not the Message Batches API. Batches would roughly halve eval cost, so they're worth adding before the five full runs budgeted in plan section 7.5.

## Datasets (`eval/datasets/`, owned by Vansh)

Gold labels have to come from people. None are generated here.

| File | One JSON object per line |
|---|---|
| `gold_turns.jsonl` | `{"move_id": 1, "child_text": "45", "teacher_text": "...", "labels": {"C1": true, "C2": false, "C3": true, "C4": false}}`: adjudicated labels from two raters |
| `ask_inscope.jsonl` | `{"question": "...", "lang": "hi", "gold": ["NISHTHA FLN Course 9: Foundational Numeracy, Module 3, §3.2"]}`: gold labels use the exact format of the ingested chunk labels; a parent section also accepts its subsections |
| `ask_oos.jsonl` | `{"question": "...", "lang": "en"}`: salary, transfers, medical, politics, Grade 8 algebra, and so on |

The `--from-rubrics` set for the coach is the labelled examples in `backend/app/content/rubrics/`. It catches regressions, but it can't stand in for the human κ set because the same examples are shown to the coach as few-shots.
