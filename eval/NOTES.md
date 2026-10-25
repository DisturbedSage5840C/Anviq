# Reading the evaluation results

`report.md` is generated from `results/*.json` and shows each number against its slide-9 target. It does not explain the numbers. This file does. Every figure below comes from the JSON files next to it, run on the demo server on 2026-10-25.

## AI child keeps its misconception: 98.3% raw, passes the 95% target

720 turns (12 malrules x 12 teacher styles x 5 problems), Riya only, Hindi and English. Re-run on the demo server on 2026-10-25 after the prompt fix in commit c91ec14, and again after a second small prompt edit (Hindi danda counted as a sentence end, a hesitate exception, a longer list of forbidden words).

| What was measured | Rate |
|---|---|
| First model reply passes every check (the metric in the report) | 98.3% |
| Passes after one regeneration with a stricter prompt | 99.4% |
| Falls back to the fixed in-character sentence | 0.6% |

- A reply passes if it states the child's computed (wrong) answer, stays within two short sentences, never admits to being an AI, and never states the right answer.
- Target is at least 95% raw and at least 90% for each malrule. The lowest malrule is 95.0% (PV.CONCAT_WRITE). The lowest teacher style is ai_probe, 93.3%, then check and rude at 96.7%.
- Every line a teacher hears passes these checks. The fixed fallback sentence is covered by a test for every malrule, so the product never breaks character even when the model slips.
- What was wrong, and what fixed it. A diagnosis of 432 replies (12 styles x 12 malrules x 3 problems) showed three causes: a third sentence when the teacher asked the child to explain (most failures), the answer written as a word ("twenty-six") where the check looks for the digits, and the child using the word "AI" even to deny being one. The prompt now asks for two sentences whatever the teacher says, digits only, at most one step, and never the words AI/robot/computer/bot. The check itself was not loosened. The diagnosis pass rate went from 69% to 98%, and the full run confirms it.
- Earlier history on the same run: 17.9% raw before the 2026-10-25 thinking-token fix (Haiku 5.5 spent its whole budget on hidden thinking and returned no text), then 70.0% raw and 85.8% after regeneration with that fix alone.
- Limits: one child (Riya) and five problems per cell. Aman and Meena have not been run through the full harness. Remaining misses are the "leading" style repeating the teacher's wrong number, and rare Hindi denials of being an AI.

## Coach agrees with experts: mean kappa 0.967, passes

150 turns from `datasets/gold_turns.jsonl`. This set is owned by Vansh. Do not describe it as double-rater, human-adjudicated gold unless that is confirmed, and do not quote this figure to judges until it is.

## Citations: right course on 58% of answers, exact section 0%, both below target. Out-of-scope refusal 100%, false refusals 22-28%

- Out-of-scope questions (salary, transfers and so on) are refused every time (40 of 40).
- First run: 851 chunks (447 English, 404 Hindi), all from the combined NISHTHA FLN course books, no NIPUN Bharat text. False refusals were 72%.
- Second run, after loading the NIPUN Bharat guidelines (289 chunks, corpus now 1,140): false refusals fell to 62%. Questions the NIPUN text covers are now answered with citations (checked by hand on the VM).
- Third run (commit 1ff3675): false refusals fell to 41% and answered in-scope questions rose from 37 to 65 of 100. Two causes were fixed. The cited-answer call let hidden thinking use the whole token cap, so some replies had no text (it now runs with thinking off; Sonnet 5.5 wants `between_tools`, Haiku takes `disabled`). The search also let filler words ("how", "the", Hindi "के", "में") outrank content words, so `or_query` now drops them. Out-of-scope refusal stayed at 40 of 40.
- Fourth run (this change): the official NISHTHA FLN English and Hindi books are single files holding all twelve courses, so the manifest now gives each course its page range (`first_page`, `last_page`) and every chunk is cited with its course ("NISHTHA FLN Course 9: Foundational Numeracy"). The NISHTHA rows were reloaded (817 chunks, NIPUN's 289 kept; 1,106 in all). Results on the same 100 + 40 questions: right course cited on 73.0% of answered in-scope questions (new `course_citation_correct_rate`), exact "Module N, §N.M" match still 0.0%, false refusals 37% (was 41%), out-of-scope refused 40 of 40.
- Fifth and sixth runs (commits a793753 and da65d66, BM25 search): Postgres `ts_rank_cd` has no idea how rare a word is, so a generic course-overview page that repeats "teaching" and "approach" outranked the passage holding the one rare word the question was about. The search now ranks the whole corpus in memory with BM25 (`app/core/ask/bm25.py`), which weights words by rarity. Hindi sentences also now split at the danda, and the doubled marks of the garbled Hindi PDF text ("सेे", "बच््चोों") collapse to one. Results on the same 100 + 40 questions: false refusals 22% (BM25 only) and 28% (with the mark fix); out-of-scope refused 40 of 40 both times; right course cited on 60.3% and 58.3% of the answered questions. The two runs differ by more than the change between them should explain, so read this as run-to-run spread of about 6 points on 100 questions, not a trend. Note the course-level rate now covers 72-78 answered questions instead of 63, so it is not directly comparable with the 73% above.
- Why false refusals stay high: for refused questions the search returns six passages and the model correctly says the passages do not cover it. Offline replay: the gold course is in the top 6 for 77 of 100 questions, top 10 for 82, top 12 for 82, so a bigger window barely helps (`TOP_K` stays 6). The corpus has "ELPS" in 78 rows but "bundle" in one and the Hindi word for it in none, so several gold questions look unanswerable from the ingested text. That is a corpus or gold-set gap that code cannot close.
- The retrieval score cannot gate scope: BM25's best-possible-score share ranks passages but does not separate in-scope from out-of-scope questions (every out-of-scope question still had a top score above the in-scope 5th percentile). Scope stays decided by the question rewrite plus the model's refusal; the score is only a low floor.
- Why the exact-section number stays at 0%: the gold labels name a Module and § (for example "Course 9 ..., Module 3, §3.2"), but the combined book's own headings do not follow that numbering (Course 9 has five numbered sections, for example), so a label like that cannot equal our citation line however good the answer is. The course-level rate is the fair measure of "did it cite the right place" until the gold is relabelled. It is still below the 95% target.
- Some Hindi pages (one to five per course) extract as scanned or garbled text and need OCR; they are in the corpus but will not match well.
- Chunker bug found and fixed on the way (commit 326a0d1): a numbered heading such as 6.5 was being read as a module, so NIPUN chunks were cited as "Module 6". A module now comes only from an explicit Module/Unit/Section heading.
- Gold labels come from people. Do not regenerate them from the system's own retrieval. Relabel against the labels actually in `doc_chunks` (Vansh owns the set), at course level or with the book's own section numbers.
- What is verified: out-of-scope questions are refused, and in-scope questions the corpus covers are answered with citations from the right course about three times in five. What is not: the 95% citation target, and the 5% false-refusal limit (now 22-28%). Do not claim either to judges.

## Cost per teacher-day: not a valid measurement yet

- The stored figure ($0.220) comes from the last 7 days of mostly test traffic: 2 teacher-days, 37 model calls.
- It is inflated. Rows written before the 2026-10-25 fix used old Haiku pricing. The eval (`app/evaluation/latency_cost.py`) now recomputes model spend from the stored token counts at the current price table instead of reading the stored estimate, so old rows cannot distort the figure.
- Prices were checked on 2026-10-25 against Anthropic's pricing page (Haiku 5.5 US$0.10/0.50, Sonnet 5.5 US$2/10, Opus 5.5 US$4/20 per million tokens) and Sarvam's price list (speech-to-text Rs 29.40 per hour, Bulbul V3 text-to-speech Rs 30 per 10,000 characters). The same check found one wrong number: a cache hit costs 0.05 of the input price on Sonnet 5.5 and Opus 5.5, not 0.1, and the table now says so. The Google speech rates were not re-checked.
- Re-pricing the stored token counts plus the recorded speech cost gives roughly US$0.15 per teacher-day, about a third of it speech. Sarvam's cheaper Bulbul V4 Flash voice or a volume plan would lower the speech share.
- The deck's target of about US$0.05 per teacher-day is not supported by any measurement yet. It needs a real pilot day, or a replay of full sessions, with prices confirmed.

## Latency

Model latency per purpose is in `report.md` (median: child 1.5 s, Ask answer 1.8 s, plan 2.7 s, coach 3.8 s). End-to-end turn latency, including speech and WhatsApp, has not been measured.
