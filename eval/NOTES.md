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

## Citations: 0% correct, below target. Out-of-scope refusal 100%, false refusals 62%

- Out-of-scope questions (salary, transfers and so on) are refused every time (40 of 40).
- First run: 851 chunks (447 English, 404 Hindi), all from the combined NISHTHA FLN course books, no NIPUN Bharat text. False refusals were 72%.
- Second run, after loading the NIPUN Bharat guidelines (289 chunks, corpus now 1,140): false refusals fell to 62%. Questions the NIPUN text covers are now answered with citations (checked by hand on the VM).
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
