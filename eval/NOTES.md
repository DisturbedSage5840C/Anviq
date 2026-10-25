# Reading the evaluation results

`report.md` is generated from `results/*.json` and shows each number against its slide-9 target. It does not explain the numbers. This file does. Every figure below comes from the JSON files next to it, run on the demo server on 2026-10-25.

## AI child keeps its misconception: 70.0% raw, below the 95% target

720 turns (12 malrules x 12 teacher styles x 5 problems), Riya only, Hindi and English.

| What was measured | Rate |
|---|---|
| First model reply passes every check (the metric in the report) | 70.0% |
| Passes after one regeneration with a stricter prompt | 85.8% |
| Falls back to the fixed in-character sentence | 14.2% |

- A reply passes if it states the child's computed (wrong) answer, stays within two short sentences, never admits to being an AI, and never states the right answer.
- Every line a teacher hears passes these checks. The fixed fallback sentence is covered by a test for every malrule. So the product does not break character. The gap is how often the child speaks from a script instead of the model.
- Weakest teacher styles on the first reply: Hinglish prompts (43%), rude (55%), long (58%) and praise (60%). For Hinglish, the failure seen in samples was a third sentence. The other weak styles have not been diagnosed.
- Before the 2026-10-25 fix (Haiku 5.5 spent its whole token budget on hidden thinking and returned no text) the same run scored 17.9% raw and 24.0% after regeneration.
- Not yet done: tuning the prompt for the weak styles. The run had one transient network retry.

## Coach agrees with experts: mean kappa 0.967, passes

150 turns from `datasets/gold_turns.jsonl`. This set is owned by Vansh. Do not describe it as double-rater, human-adjudicated gold unless that is confirmed, and do not quote this figure to judges until it is.

## Citations: 0% correct, below target. Out-of-scope refusal 100%, false refusals 72%

- Out-of-scope questions (salary, transfers and so on) are refused every time.
- Almost every genuine in-scope question is also refused. The cause is the corpus, not the answering pipeline. The ingested corpus is 851 chunks (447 English, 404 Hindi), all from the general NISHTHA FLN course books. It has no NIPUN Bharat guidelines and no Course 9 numeracy text.
- The in-scope question set was labelled against sources we do not have, so it cannot be answered from what is loaded.
- Fix: ingest the missing sources, or re-label the question set to the loaded corpus. Until then, Ask Anviq's coverage is limited and this number says so.

## Cost per teacher-day: not a valid measurement yet

- The stored figure ($0.220) comes from the last 7 days of mostly test traffic: 2 teacher-days, 37 model calls.
- It is inflated. Rows written before the 2026-10-25 fix used old Haiku pricing, and the eval re-reads stored costs instead of recomputing them.
- Re-pricing the same token counts at the current price table (Haiku 5.5 US$0.10/0.50, Sonnet 5.5 US$2/10 per million tokens) plus the recorded speech cost gives roughly US$0.15 per teacher-day, about a third of it speech. These prices are assumptions in `app/llm/client.py` and have not been checked against the console.
- The deck's target of about US$0.05 per teacher-day is not supported by any measurement yet. It needs a real pilot day, or a replay of full sessions, with prices confirmed.

## Latency

Model latency per purpose is in `report.md` (median: child 1.5 s, Ask answer 1.8 s, plan 2.7 s, coach 3.8 s). End-to-end turn latency, including speech and WhatsApp, has not been measured.
