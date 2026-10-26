import json
from pathlib import Path

import pytest

from app.core.ask.answer import AskReply
from app.core.ask.chunking import SourceDoc
from app.core.ask.ingest import looks_broken, pages_in_range, read_manifest
from app.core.children.registry import ALL_RULES
from app.evaluation import character, coach_kappa
from app.evaluation.citations import course_of, label_matches, question_details, score
from app.evaluation.metrics import cohen_kappa, percentile, rate
from app.evaluation.report import render


def test_kappa_is_one_for_perfect_agreement_and_zero_for_chance():
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert cohen_kappa([True, True, False, False], [True, False, True, False]) == pytest.approx(0.0)


def test_kappa_matches_a_worked_example():
    a = [True] * 20 + [False] * 5 + [True] * 10 + [False] * 15
    b = [True] * 20 + [True] * 5 + [False] * 10 + [False] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)


def test_kappa_on_a_constant_criterion_does_not_flatter_disagreement():
    assert cohen_kappa([True, True], [True, True]) == 1.0
    with pytest.raises(ValueError):
        cohen_kappa([], [])


def test_percentile_and_rate():
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert rate(1, 4) == 0.25 and rate(1, 0) == 0.0


def test_full_character_run_is_3600_turns_across_every_rule_and_style():
    cases = character.cases(ALL_RULES, 25, 1)
    assert len(cases) == 3600
    assert {c.rule_id for c in cases} == {r.id for r in ALL_RULES}
    assert {c.style for c in cases} == {s[0] for s in character.STYLES}
    assert {c.lang for c in cases} == {"hi", "en"}


async def test_character_harness_offline_passes_and_reports_per_rule():
    report = await character.run(character.ScriptedChild(), character.cases(ALL_RULES, 1, 1), 4)
    assert report["raw_rate"] == 1.0 and report["pass"] is True
    assert len(report["by_malrule"]) == 12  # type: ignore[arg-type]


class LeakyChild:
    async def speak(self, brief):  # type: ignore[no-untyped-def]
        return f"{brief.correct}"


async def test_character_harness_catches_a_child_that_gives_the_right_answer():
    report = await character.run(LeakyChild(), character.cases(ALL_RULES, 1, 1), 4)
    assert report["raw_rate"] == 0.0 and report["pass"] is False


async def test_coach_harness_offline_agrees_perfectly_with_itself():
    gold = coach_kappa.gold_from_rubrics()
    report = await coach_kappa.run(coach_kappa.Oracle(gold), gold, 4)
    assert report["mean_kappa"] == 1.0 and report["pass"] is True
    assert "1:C1" in report["kappa_by_criterion"]  # type: ignore[operator]


def test_gold_file_loads(tmp_path: Path):
    path = tmp_path / "gold.jsonl"
    path.write_text(
        json.dumps({"move_id": 1, "teacher_text": "t", "labels": {"C1": True}}) + "\n\n",
        encoding="utf-8",
    )
    (row,) = coach_kappa.load_gold(path)
    assert row.labels == {"C1": True} and row.child_text == ""


def test_a_subsection_counts_as_citing_its_gold_section():
    assert label_matches("NISHTHA FLN Course 9, §3.2", "NISHTHA FLN Course 9, §3")
    assert label_matches("A, §3", "A, §3")
    assert not label_matches("A, §31", "A, §3")


def test_module_numbers_match_with_or_without_leading_zeros() -> None:
    # The English NISHTHA book pads course 6 modules ("Module 05"); the Hindi one does not.
    course = "NISHTHA FLN Course 6: Foundational Language and Literacy"
    assert label_matches(f"{course}, Module 5", f"{course}, Module 05")
    assert label_matches(f"{course}, Module 05, §5.1", f"{course}, Module 5, §5")
    assert not label_matches(f"{course}, Module 15", f"{course}, Module 5")
    assert not label_matches(f"{course}, Module 5", f"{course}, Module 6")


def _reply(sources: tuple[str, ...], refused: bool) -> AskReply:
    return AskReply("t", "t", sources, refused)


def test_citation_scoring_separates_accuracy_refusal_and_false_refusal():
    inscope = [
        ({"gold": ["A, §1"]}, _reply(("A, §1.2",), False)),
        ({"gold": ["A, §2"]}, _reply(("B, §9",), False)),
        ({"gold": ["A, §3"]}, _reply((), True)),
        ({"gold": ["A, §4"]}, None),
    ]
    oos = [_reply((), True), _reply(("X",), False)]
    report = score(inscope, oos)
    assert report["citation_correct_rate"] == 0.5
    assert report["false_refusal_rate"] == 0.25
    assert report["oos_refusal_rate"] == 0.5
    assert report["unavailable"] == 1 and report["pass"] is False


def test_corpus_gap_questions_are_scored_apart_and_never_change_the_verdict():
    inscope = [({"gold": ["A, §1"]}, _reply(("A, §1",), False))]
    oos = [_reply((), True)]
    gap = [_reply((), True), _reply(("A, §9",), False), None]
    with_gap = score(inscope, oos, gap)
    assert with_gap["corpus_gap"] == 3
    assert with_gap["corpus_gap_refusal_rate"] == pytest.approx(1 / 3)
    assert with_gap["unavailable"] == 1
    assert with_gap["false_refusal_rate"] == 0.0
    assert with_gap["pass"] is True
    assert score(inscope, oos)["corpus_gap"] == 0


def test_report_says_not_run_rather_than_pass_when_results_are_missing(tmp_path: Path):
    text = render(tmp_path)
    assert "not run" in text and "PASS" not in text


def test_report_labels_offline_runs_as_harness_checks(tmp_path: Path):
    (tmp_path / "character.json").write_text(
        json.dumps(
            {"turns": 1, "raw_rate": 1.0, "pass": True, "offline": True,
             "by_malrule": {"X": 1.0}, "by_style": {"s": 1.0}}
        ),
        encoding="utf-8",
    )  # fmt: skip
    text = render(tmp_path)
    assert "harness check only" in text and "| X | 100.0% |" in text


def test_report_judges_citations_and_refusals_on_their_own_rates(tmp_path: Path):
    (tmp_path / "citations.json").write_text(
        json.dumps(
            {"citation_correct_rate": 0.945, "course_citation_correct_rate": 0.978,
             "oos_refusal_rate": 1.0, "false_refusal_rate": 0.0, "pass": False}
        ),
        encoding="utf-8",
    )  # fmt: skip
    rows = {
        line.split("|")[1].strip(): line
        for line in render(tmp_path).splitlines()
        if line.startswith("|")
    }
    assert rows["Citations correct"].rstrip().endswith("below target |")
    assert rows["Out-of-scope refused"].rstrip().endswith("PASS |")


def test_manifest_rows_become_source_documents(tmp_path: Path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,source,course_no,course_title,lang\nc9.pdf,NISHTHA FLN,9,Numeracy,hi\nn.pdf,NIPUN Bharat,,,en\n",
        encoding="utf-8",
    )
    (first, doc1), (_, doc2) = read_manifest(manifest)
    assert first == tmp_path / "c9.pdf"
    assert (doc1.course_no, doc1.lang) == (9, "hi") and doc2.course_no is None


def test_manifest_rows_can_name_the_pages_of_one_course_inside_a_combined_book(tmp_path: Path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,source,course_no,course_title,lang,first_page,last_page\n"
        "book.pdf,NISHTHA FLN,9,Numeracy,en,418,465\n"
        "book.pdf,NISHTHA FLN,10,Leadership,en,,\n",
        encoding="utf-8",
    )
    (_, nine), (_, ten) = read_manifest(manifest)
    assert (nine.first_page, nine.last_page) == (418, 465)
    assert (ten.first_page, ten.last_page) == (None, None)


def test_only_the_pages_in_a_courses_range_are_kept():
    pages = [(n, f"page {n}") for n in range(1, 11)]
    doc = SourceDoc("NISHTHA FLN", 9, "Numeracy", "en", first_page=4, last_page=6)
    assert [n for n, _ in pages_in_range(pages, doc)] == [4, 5, 6]
    whole = SourceDoc("NIPUN Bharat", None, "", "en")
    assert len(pages_in_range(pages, whole)) == 10


def test_a_citation_is_reduced_to_its_course_whatever_commas_the_title_has():
    ict = "NISHTHA FLN Course 11: Integration of ICT in Teaching, Learning and Assessment"
    assert course_of(f"{ict}, Module 2, §2.1") == ict
    assert course_of("NISHTHA FLN Course 9: Foundational Numeracy, Module 3") == (
        "NISHTHA FLN Course 9: Foundational Numeracy"
    )
    assert course_of("NIPUN Bharat, §17.6") == "NIPUN Bharat"
    assert course_of("NIPUN Bharat") == "NIPUN Bharat"


def test_course_level_accuracy_is_reported_next_to_the_strict_section_level_rate():
    inscope = [
        ({"gold": ["A Course 1: X, Module 3, §3.2"]}, _reply(("A Course 1: X, Module 1, §1.1",), False)),
        ({"gold": ["A Course 2: Y, Module 1, §1.1"]}, _reply(("A Course 3: Z, Module 1",), False)),
    ]  # fmt: skip
    report = score(inscope, [])
    assert report["course_citation_correct_rate"] == 0.5
    assert report["citation_correct_rate"] == 0.0


def test_question_details_name_each_failure_without_the_answer_text():
    inscope = [
        ({"question": "q1", "lang": "en", "gold": ["A Course 1: X, §1"]}, _reply(("A Course 1: X, §1.2",), False)),
        ({"question": "q2", "lang": "hi", "gold": ["A Course 2: Y, §1"]}, _reply((), True)),
        ({"question": "q3", "gold": ["A Course 3: Z"]}, _reply(("A Course 1: X, §1",), False)),
        ({"question": "q4", "gold": ["A Course 3: Z"]}, None),
    ]  # fmt: skip
    rows = question_details(inscope)
    assert [(r["outcome"], r["course_correct"]) for r in rows] == [
        ("answered", True),
        ("refused", False),
        ("answered", False),
        ("unavailable", False),
    ]
    assert rows[2]["lang"] == "hi"
    assert all("text" not in r and "spoken" not in r for r in rows)


def test_report_shows_the_course_level_citation_rate_only_when_it_was_recorded(tmp_path: Path):
    old = {"citation_correct_rate": 0.0, "oos_refusal_rate": 1.0, "false_refusal_rate": 0.4}
    (tmp_path / "citations.json").write_text(json.dumps(old), encoding="utf-8")
    assert "| 0.0% |" in render(tmp_path)
    new = {**old, "citation_correct_rate": 0.1, "course_citation_correct_rate": 0.75}
    (tmp_path / "citations.json").write_text(json.dumps(new), encoding="utf-8")
    assert "10.0% section-level, 75.0% course-level" in render(tmp_path)


def test_report_names_how_many_questions_the_books_cannot_answer(tmp_path: Path):
    results = {
        "citation_correct_rate": 0.9, "oos_refusal_rate": 1.0, "false_refusal_rate": 0.0,
        "corpus_gap": 9, "corpus_gap_refusal_rate": 0.5,
    }  # fmt: skip
    (tmp_path / "citations.json").write_text(json.dumps(results), encoding="utf-8")
    text = render(tmp_path)
    assert "9 questions the books do not answer" in text and "50.0%" in text


def test_report_shows_end_to_end_latency_with_its_sample_size(tmp_path: Path):
    results = {
        "all": {"n": 45, "p50_ms": 5738, "p95_ms": 9965, "max_ms": 10190},
        "target": {"p50_ms": 10000, "p95_ms": 20000},
    }
    (tmp_path / "latency_e2e.json").write_text(json.dumps(results), encoding="utf-8")
    rows = {
        line.split("|")[1].strip(): line
        for line in render(tmp_path).splitlines()
        if line.startswith("|")
    }
    row = rows["End-to-end latency (web room)"]
    assert "p50 5.7 s" in row and "p95 10.0 s" in row and "45 turns" in row
    assert row.rstrip().endswith("PASS |")


def test_report_fails_end_to_end_latency_when_either_percentile_misses(tmp_path: Path):
    results = {
        "all": {"n": 10, "p50_ms": 11000, "p95_ms": 15000, "max_ms": 16000},
        "target": {"p50_ms": 10000, "p95_ms": 20000},
    }
    (tmp_path / "latency_e2e.json").write_text(json.dumps(results), encoding="utf-8")
    assert "below target" in render(tmp_path)


def test_a_hindi_page_without_devanagari_is_flagged_for_ocr():
    assert looks_broken("abcdefghij " * 10, "hi")
    assert not looks_broken("बच्चों को बंडल से गिनती सिखाएँ " * 5, "hi")
    assert not looks_broken("abcdefghij " * 10, "en")


def test_shipped_eval_datasets_and_manifests_are_well_formed():
    from app.core.rubric import load_rubric
    from app.evaluation.citations import _jsonl
    from app.speech.benchmark import load_manifest as load_stt_manifest

    repo_root = Path(__file__).parents[3]
    gold = coach_kappa.load_gold(repo_root / "eval" / "datasets" / "gold_turns.jsonl")
    assert len(gold) == 150
    assert {g.move_id for g in gold} == {1, 2}
    for row in gold:
        rubric = load_rubric(row.move_id)
        assert set(row.labels) == set(rubric.criterion_ids)

    inscope = _jsonl(repo_root / "eval" / "datasets" / "ask_inscope.jsonl")
    oos = _jsonl(repo_root / "eval" / "datasets" / "ask_oos.jsonl")
    gap = _jsonl(repo_root / "eval" / "datasets" / "ask_corpus_gap.jsonl")
    assert len(inscope) == 91
    assert len(gap) == 9
    assert len(inscope) + len(gap) == 100
    assert all(q["question"] and q["lang"] in {"hi", "en"} and "gold" not in q for q in gap)
    assert not {q["question"] for q in gap} & {q["question"] for q in inscope}
    assert len(oos) == 40
    assert all(q.get("question") and q.get("gold") for q in inscope)
    assert all(q.get("question") and q.get("lang") in {"hi", "en"} for q in oos)

    corpus_docs = read_manifest(repo_root / "content" / "corpus" / "manifest.csv")
    assert sorted((doc.source, doc.lang) for _, doc in corpus_docs) == (
        [("NCERT Teachers' Handbook Class 1-2", "en"), ("NIPUN Bharat", "en")]
        + [("NISHTHA FLN", "en")] * 12
        + [("NISHTHA FLN", "hi")] * 12
    )
    for lang in ("en", "hi"):
        courses = [d for _, d in corpus_docs if d.source == "NISHTHA FLN" and d.lang == lang]
        assert sorted(d.course_no or 0 for d in courses) == list(range(1, 13))
        assert all(d.first_page and d.last_page and d.first_page <= d.last_page for d in courses)
    assert all(path.suffix == ".pdf" for path, _ in corpus_docs)

    stt_clips = load_stt_manifest(repo_root / "eval" / "datasets" / "stt_clips" / "manifest.csv")
    assert len(stt_clips) == 30
