# Second labeller sheet for the coach kappa

Purpose: the 150-turn gold set was labelled by one person (Vansh). Kappa is only a fair test of the coach if a *second person* labels the same turns without seeing those labels. This sheet has no gold labels on it.

## How to fill it

1. Open `kappa_second_labeller.csv` in Google Sheets or Excel. Do not open `kappa_second_labeller_key.csv` or `../datasets/gold_turns.jsonl` until you finish.
2. For each row read what the teacher said, then for C1 to C4 of that move write `1` if the teacher's line meets the criterion, `0` if not. Judge the teacher line only; the child text is context.
3. Every row is from Move 1 or Move 2, and both have four criteria, so fill all four columns on every row.
4. Save as CSV and give it back. Then run, from `backend/`:
   `uv run python -m app.evaluation.kappa_compare --sheet ../eval/review/<filled file>.csv`
   It prints Cohen's kappa between the two labellers (same bar as the coach: mean >= 0.6, none < 0.5) and writes `eval/results/kappa_second_labeller.json` and `kappa_second_labeller_result.md`. A sheet with a blank or non-0/1 cell is refused, not scored.

## Criteria by move

### Move 1: Ask how, not just what
- **C1**: Asks for the child's process or reason (how / why / show me), not only the answer.
- **C2**: Is not a closed question: not yes/no and not a single recall or calculation answer.
- **C3**: Refers to the specific child's own answer or work, not to the class in general.
- **C4**: Invites a representation: bundles, sticks, fingers, a drawing, or showing it.

### Move 2: Use the wrong answer
- **C1**: Does not label the answer wrong (no 'wrong', 'no', 'incorrect') before the child has explained.
- **C2**: Asks the child to explain their own method or thinking.
- **C3**: Invites another child to compare, respond or weigh in.
- **C4**: Frames the mistake as useful or interesting for the whole class to learn from.
