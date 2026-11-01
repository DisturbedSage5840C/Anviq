import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.ask.answer import AskReply
from app.evaluation.citations import (
    _ask,
    corpus_of,
    course_of,
    label_matches,
    load_eval_sets,
    score,
)

BOOK = "NCERT Class 3 Maths Mela"


@pytest.mark.parametrize(
    "cited",
    [
        f"{BOOK}, Ch 4, p.12",
        f"{BOOK}, Ch 4: Fun with Shapes, p.12",
        f"{BOOK}, Ch 4",
    ],
)
def test_a_chapter_gold_accepts_any_page_of_that_chapter(cited: str):
    assert label_matches(cited, f"{BOOK}, Ch 4")


@pytest.mark.parametrize(
    "cited",
    [f"{BOOK}, Ch 41, p.2", f"{BOOK}, Ch 5, p.12", "NCERT Class 4 Maths Mela, Ch 4, p.12"],
)
def test_a_chapter_gold_rejects_another_chapter_or_class(cited: str):
    assert not label_matches(cited, f"{BOOK}, Ch 4")


def test_a_book_gold_accepts_every_chapter_of_that_book():
    assert label_matches(f"{BOOK}, Ch 9: Title, p.3", BOOK)


def test_a_book_gold_does_not_accept_a_book_whose_title_only_starts_the_same():
    assert not label_matches("NCERT Class 3 Maths Mela Extra, Ch 1, p.1", BOOK)


def test_a_page_gold_accepts_only_that_page():
    assert label_matches(f"{BOOK}, Ch 4, p.12", f"{BOOK}, Ch 4, p.12")
    assert not label_matches(f"{BOOK}, Ch 4, p.120", f"{BOOK}, Ch 4, p.12")


@pytest.mark.parametrize(
    ("label", "book"),
    [
        (f"{BOOK}, Ch 4, p.12", BOOK),
        (f"{BOOK}, Ch 4: Fun, Fast and Fair, p.12", BOOK),
        (BOOK, BOOK),
    ],
)
def test_course_of_reduces_a_textbook_label_to_its_book(label: str, book: str):
    assert course_of(label) == book


def test_corpus_of_tells_textbooks_from_guidance_documents():
    assert corpus_of(f"{BOOK}, Ch 4, p.12") == "textbook"
    assert corpus_of("NISHTHA FLN Course 9, §3.2") == "guidance"
    assert corpus_of("NIPUN Bharat, §5") == "guidance"


def _reply(*sources: str) -> AskReply:
    return AskReply(text="t", spoken="t", sources=tuple(sources), refused=False)


def test_score_reports_old_and_new_corpus_separately():
    textbook_q = {"question": "q1", "gold": [f"{BOOK}, Ch 4"]}
    guidance_q = {"question": "q2", "gold": ["NISHTHA FLN Course 9, §3"]}
    inscope = [
        (textbook_q, _reply(f"{BOOK}, Ch 4, p.2")),
        (guidance_q, _reply("NISHTHA FLN Course 2, §1")),
    ]

    report: dict[str, Any] = score(inscope, [])

    by_corpus = report["citation_by_corpus"]
    assert by_corpus["textbook"] == {"answered": 1, "correct": 1, "rate": 1.0}
    assert by_corpus["guidance"] == {"answered": 1, "correct": 0, "rate": 0.0}


class _RecordingAsk:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None]] = []

    async def answer(self, question: str, lang: str, grade: int | None = None) -> AskReply:
        self.calls.append((question, lang, grade))
        return _reply()


def test_a_question_with_a_class_is_asked_for_that_class():
    ask = _RecordingAsk()

    asyncio.run(
        _ask(ask, {"question": "q", "lang": "en", "grade": 4}, asyncio.Semaphore(1))  # type: ignore[arg-type]
    )

    assert ask.calls == [("q", "en", 4)]


def test_a_question_without_a_class_is_asked_with_no_class_limit():
    ask = _RecordingAsk()

    asyncio.run(_ask(ask, {"question": "q"}, asyncio.Semaphore(1)))  # type: ignore[arg-type]

    assert ask.calls == [("q", "hi", None)]


def test_score_reports_dev_and_held_out_questions_separately():
    dev_q = {"question": "q1", "gold": [f"{BOOK}, Ch 4"], "split": "dev"}
    held_q = {"question": "q2", "gold": [f"{BOOK}, Ch 5"], "split": "held_out"}
    old_q = {"question": "q3", "gold": ["NISHTHA FLN Course 9, §3"]}
    inscope = [
        (dev_q, _reply(f"{BOOK}, Ch 4, p.2")),
        (held_q, _reply(f"{BOOK}, Ch 9, p.2")),
        (old_q, _reply("NISHTHA FLN Course 9, §3.1")),
    ]

    report: dict[str, Any] = score(inscope, [])

    by_split = report["citation_by_split"]
    assert by_split["dev"] == {"answered": 1, "correct": 1, "rate": 1.0}
    assert by_split["held_out"] == {"answered": 1, "correct": 0, "rate": 0.0}
    assert "unsplit" not in by_split


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_load_eval_sets_appends_the_textbook_files_when_present(tmp_path: Path):
    _write(tmp_path / "ask_inscope.jsonl", [{"question": "a", "gold": ["x"]}])
    _write(tmp_path / "ask_oos.jsonl", [{"question": "b"}])
    _write(tmp_path / "ask_corpus_gap.jsonl", [{"question": "c"}])
    _write(tmp_path / "ask_textbook_inscope.jsonl", [{"question": "d", "gold": [BOOK]}])
    _write(tmp_path / "ask_textbook_oos.jsonl", [{"question": "e"}])
    _write(tmp_path / "ask_textbook_gap.jsonl", [{"question": "f"}])

    inscope, oos, gap = load_eval_sets(tmp_path)

    assert [q["question"] for q in inscope] == ["a", "d"]
    assert [q["question"] for q in oos] == ["b", "e"]
    assert [q["question"] for q in gap] == ["c", "f"]


def test_load_eval_sets_works_without_the_textbook_files(tmp_path: Path):
    _write(tmp_path / "ask_inscope.jsonl", [{"question": "a", "gold": ["x"]}])
    _write(tmp_path / "ask_oos.jsonl", [{"question": "b"}])

    inscope, oos, gap = load_eval_sets(tmp_path)

    assert len(inscope) == 1 and len(oos) == 1 and gap == []


def test_load_eval_sets_without_the_core_files_is_an_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_eval_sets(tmp_path)
