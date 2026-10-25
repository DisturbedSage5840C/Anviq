# Reading the evaluation results

`report.md` is generated from `results/*.json` and shows each number against its slide-9 target. It does not explain the numbers. This file does. Every figure below comes from the JSON files next to it, run on the demo server on 2026-10-25.

## AI child keeps its misconception: 98.5% raw, passes the 95% target

720 turns (12 malrules x 12 teacher styles x 5 problems), Riya only, Hindi and English. Re-run on the demo server on 2026-10-25 after the prompt fix in commit c91ec14.

| What was measured | Rate |
|---|---|
| First model reply passes every check (the metric in the report) | 98.5% |
| Passes after one regeneration with a stricter prompt | 99.6% |
| Falls back to the fixed in-character sentence | 0.4% |

- A reply passes if it states the child's computed (wrong) answer, stays within two short sentences, never admits to being an AI, and never states the right answer.
- Target is at least 95% raw and at least 90% for each malrule. The lowest malrule is 96.7% (ADD.NO_CARRY, SUB.ZERO_MINUS_N_IS_N). The lowest teacher styles are ai_probe and leading, both 95.0%.
- Every line a teacher hears passes these checks. The fixed fallback sentence is covered by a test for every malrule, so the product never breaks character even when the model slips.
- What was wrong, and what fixed it. A diagnosis of 432 replies (12 styles x 12 malrules x 3 problems) showed three causes: a third sentence when the teacher asked the child to explain (most failures), the answer written as a word ("twenty-six") where the check looks for the digits, and the child using the word "AI" even to deny being one. The prompt now asks for two sentences whatever the teacher says, digits only, at most one step, and never the words AI/robot/computer/bot. The check itself was not loosened. The diagnosis pass rate went from 69% to 98%, and the full run confirms it.
- Earlier history on the same run: 17.9% raw before the 2026-10-25 thinking-token fix (Haiku 5.5 spent its whole budget on hidden thinking and returned no text), then 70.0% raw and 85.8% after regeneration with that fix alone.
- Limits: one child (Riya) and five problems per cell. Aman and Meena have not been run through the full harness. Remaining misses are the "leading" style repeating the teacher's wrong number, and rare Hindi denials of being an AI.

## Coach agrees with experts: mean kappa 0.967, passes

150 turns from `datasets/gold_turns.jsonl`. This set is owned by Vansh. Do not describe it as double-rater, human-adjudicated gold unless that is confirmed, and do not quote this figure to judges until it is.

## Citations: 0% correct, below target. Out-of-scope refusal 100%, false refusals 41%

- Out-of-scope questions (salary, transfers and so on) are refused every time (40 of 40).
- First run: 851 chunks (447 English, 404 Hindi), all from the combined NISHTHA FLN course books, no NIPUN Bharat text. False refusals were 72%.
- Second run, after loading the NIPUN Bharat guidelines (289 chunks, corpus now 1,140): false refusals fell to 62%. Questions the NIPUN text covers are now answered with citations (checked by hand on the VM).
- Third run (commit 1ff3675): false refusals fell to 41% and answered in-scope questions rose from 37 to 65 of 100. Two causes were fixed. The cited-answer call let hidden thinking use the whole token cap, so some replies had no text (it now runs with thinking off; Sonnet 5.5 wants `between_tools`, Haiku takes `disabled`). The search also let filler words ("how", "the", Hindi "के", "में") outrank content words, so `or_query` now drops them. Out-of-scope refusal stayed at 40 of 40.
- Citation accuracy stays at 0% because the in-scope gold labels cannot match what is loaded. The set was labelled against per-course books ("NISHTHA FLN Course 9: Foundational Numeracy, Module 3, section 3.2"), but we hold only the single combined course book, with no course number, and NIPUN Bharat, which has no modules. A label like that can never equal our citation line, so this number mostly measures the label mismatch, not answer quality.
- Chunker bug found and fixed on the way (commit 326a0d1): a numbered heading such as 6.5 was being read as a module, so NIPUN chunks were cited as "Module 6". A module now comes only from an explicit Module/Unit/Section heading.
- Gold labels come from people. Do not regenerate them from the system's own retrieval. Either relabel against the labels actually in `doc_chunks` (Vansh owns the set), or add the per-course NISHTHA books, which needs an explicit download.
- What is verified: out-of-scope questions are refused, and in-scope questions the corpus covers are answered with citations. What is not: the 95% citation-accuracy target.

## Cost per teacher-day: not a valid measurement yet

- The stored figure ($0.220) comes from the last 7 days of mostly test traffic: 2 teacher-days, 37 model calls.
- It is inflated. Rows written before the 2026-10-25 fix used old Haiku pricing, and the eval re-reads stored costs instead of recomputing them.
- Re-pricing the same token counts at the current price table (Haiku 5.5 US$0.10/0.50, Sonnet 5.5 US$2/10 per million tokens) plus the recorded speech cost gives roughly US$0.15 per teacher-day, about a third of it speech. These prices are assumptions in `app/llm/client.py` and have not been checked against the console.
- The deck's target of about US$0.05 per teacher-day is not supported by any measurement yet. It needs a real pilot day, or a replay of full sessions, with prices confirmed.

## Latency

Model latency per purpose is in `report.md` (median: child 1.5 s, Ask answer 1.8 s, plan 2.7 s, coach 3.8 s). End-to-end turn latency, including speech and WhatsApp, has not been measured.
