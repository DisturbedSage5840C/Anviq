import json
from pathlib import Path

import pytest

from app.core.ask.answer import AskReply
from app.core.ask.ingest import looks_broken, read_manifest
from app.core.children.registry import ALL_RULES
from app.evaluation import character, coach_kappa
from app.evaluation.citations import label_matches, score
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


def test_manifest_rows_become_source_documents(tmp_path: Path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,source,course_no,course_title,lang\nc9.pdf,NISHTHA FLN,9,Numeracy,hi\nn.pdf,NIPUN Bharat,,,en\n",
        encoding="utf-8",
    )
    (first, doc1), (_, doc2) = read_manifest(manifest)
    assert first == tmp_path / "c9.pdf"
    assert (doc1.course_no, doc1.lang) == (9, "hi") and doc2.course_no is None


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
    assert len(inscope) == 100
    assert len(oos) == 40
    assert all(q.get("question") and q.get("gold") for q in inscope)
    assert all(q.get("question") and q.get("lang") in {"hi", "en"} for q in oos)

    corpus_docs = read_manifest(repo_root / "content" / "corpus" / "manifest.csv")
    assert len(corpus_docs) == 26

    stt_clips = load_stt_manifest(repo_root / "eval" / "datasets" / "stt_clips" / "manifest.csv")
    assert len(stt_clips) == 30
