"""The shipped textbook questions are well formed and do not overlap the older sets.

Whether each gold chapter really holds its evidence phrase needs the downloaded books, which are
not in the repository, so that check ran when the sets were built (see the build script's output)
and cannot run in CI.
"""

from pathlib import Path
from typing import Any

import pytest

from app.evaluation.citations import _jsonl, corpus_of

DATASETS = Path(__file__).parents[3] / "eval" / "datasets"
BOOK_PREFIXES = (
    "NCERT Class 1 Mridang",
    "NCERT Class 1 Joyful Mathematics",
    "NCERT Class 2 Mridang",
    "NCERT Class 2 Joyful Mathematics",
    "NCERT Class 3 Santoor",
    "NCERT Class 3 Our Wondrous World",
    "NCERT Class 3 Maths Mela",
    "NCERT Class 4 Santoor",
    "NCERT Class 4 Our Wonderous World",
    "NCERT Class 4 Math-Mela",
    "NCERT Class 5 Santoor",
    "NCERT Class 5 Our Wonderous World",
    "NCERT Class 5 Math-Mela",
)


@pytest.fixture(scope="module")
def inscope() -> list[dict[str, Any]]:
    return _jsonl(DATASETS / "ask_textbook_inscope.jsonl")


@pytest.fixture(scope="module")
def gap() -> list[dict[str, Any]]:
    return _jsonl(DATASETS / "ask_textbook_gap.jsonl")


@pytest.fixture(scope="module")
def oos() -> list[dict[str, Any]]:
    return _jsonl(DATASETS / "ask_textbook_oos.jsonl")


def test_every_in_scope_question_has_a_chapter_gold_in_a_known_book(inscope):
    assert len(inscope) == 69
    for row in inscope:
        assert row["question"].strip() and row["evidence"].strip()
        assert row["lang"] == "en" and row["grade"] in {1, 2, 3, 4, 5}
        (gold,) = row["gold"]
        assert corpus_of(gold) == "textbook"
        book, _, chapter = gold.rpartition(", Ch ")
        assert book in BOOK_PREFIXES and chapter.isdigit()
        assert f"Class {row['grade']} " in book


def test_every_in_scope_question_is_in_the_dev_or_held_out_split(inscope):
    splits = {row["split"] for row in inscope}
    assert splits == {"dev", "held_out"}
    held_out = sum(row["split"] == "held_out" for row in inscope)
    assert 0.3 <= held_out / len(inscope) <= 0.5


def test_every_class_has_in_scope_questions(inscope):
    assert {row["grade"] for row in inscope} == {1, 2, 3, 4, 5}


def test_gap_questions_have_a_class_and_no_gold(gap):
    assert len(gap) == 12
    for row in gap:
        assert row["question"].strip() and row["lang"] == "en"
        assert row["grade"] in {1, 2, 3, 4, 5}
        assert "gold" not in row


def test_out_of_scope_questions_are_english_with_no_gold(oos):
    assert len(oos) == 12
    assert all(r["question"].strip() and r["lang"] == "en" and "gold" not in r for r in oos)


def test_no_question_is_repeated_within_or_across_files(inscope, gap, oos):
    older = [
        q["question"]
        for name in ("ask_inscope", "ask_oos", "ask_corpus_gap")
        for q in _jsonl(DATASETS / f"{name}.jsonl")
    ]
    new = [q["question"] for q in (*inscope, *gap, *oos)]
    assert len(set(new)) == len(new)
    assert not set(new) & set(older)
