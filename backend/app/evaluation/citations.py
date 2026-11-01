"""Are Ask Anviq's citations right, and does it refuse what it should? Plan section 8, rows 3-4.

Targets: cited section correct on >=95% of in-scope questions; >=95% of out-of-scope questions
refused; <=5% of in-scope questions wrongly refused. Needs the corpus ingested and a model key.

    ask_inscope.jsonl:  {"question": "...", "lang": "hi", "gold": ["NISHTHA FLN Course 9, §3.2"]}
    ask_oos.jsonl:      {"question": "...", "lang": "en"}

A cited label counts as correct when it equals a gold label or is a subsection of one (gold
"...§3" accepts "...§3.2"). A textbook gold may name a book ("NCERT Class 3 Maths Mela"), a
chapter ("..., Ch 4") or a page ("..., Ch 4, p.12"); it accepts any label inside it. The report
also gives a looser course-level rate, which ignores the module and section (or, for a textbook,
the chapter and page), because the gold's numbering need not match the book's own headings. The
citation rate is also reported per corpus, "guidance" (NISHTHA, NIPUN, handbook, NCF) and
"textbook", so the textbook questions never move the guidance figure, and per "split" (dev or
held_out) for the questions that name one. The refusal rates for out-of-scope and corpus-gap
questions mix both corpora, because those questions belong to neither. The optional files
ask_textbook_inscope/oos/gap.jsonl are added to the sets when present. A question may carry a
"grade" (1-5), which limits retrieval to that class as it does for a teacher.

    python -m app.evaluation.citations --datasets ../eval/datasets
"""

import argparse
import asyncio
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.core.ask.answer import AskAnviq, AskReply, AskUnavailableError
from app.core.ask.retrieve import HybridRetriever
from app.db.corpus import postgres_bm25_search
from app.evaluation.metrics import rate
from app.llm.client import LLMClient

CITATION_TARGET = 0.95
REFUSAL_TARGET = 0.95
FALSE_REFUSAL_LIMIT = 0.05


_SECTION_TAIL = re.compile(r",\s*§[^,]*$")
_MODULE_TAIL = re.compile(r",\s*Module\s[^,]*$")
_PAGE_TAIL = re.compile(r",\s*p\.\d+$")
_CHAPTER_TAIL = re.compile(r",\s*Ch\s+\d+(?::.*)?$")
TEXTBOOK_PREFIX = "NCERT "


_MODULE_NUMBER = re.compile(r"(Module\s)0+(\d)")


def _unpadded(label: str) -> str:
    """ "Module 05" and "Module 5" name the same module; the two NISHTHA books pad differently."""
    return _MODULE_NUMBER.sub(r"\1\2", label)


def corpus_of(label: str) -> str:
    """ "textbook" for an NCERT textbook label, "guidance" for everything else."""
    return "textbook" if label.startswith(TEXTBOOK_PREFIX) else "guidance"


def label_matches(cited: str, gold: str) -> bool:
    """True when `cited` is `gold` or sits inside it (a subsection, or a chapter or page of a book).

    A guidance gold is only extended at a "." (§3 accepts §3.2). A textbook gold is also extended
    at "," or ":" (a book accepts its chapters, a chapter its pages), and never mid-word, so
    "Ch 4" does not accept "Ch 41" and a book does not accept a book whose title starts the same.
    """
    cited, gold = _unpadded(cited), _unpadded(gold)
    boundaries = (".", ",", ":") if corpus_of(gold) == "textbook" else (".",)
    return cited == gold or any(cited.startswith(f"{gold}{mark}") for mark in boundaries)


def course_of(label: str) -> str:
    """A citation without its finer parts: "NISHTHA FLN Course 9: Foundational Numeracy", or for a
    textbook "NCERT Class 3 Maths Mela".

    Only a trailing ", p.N", ", Ch N[: title]", ", §…" and then ", Module …" are removed, in that
    order, so commas inside a course title (Course 11) survive.
    """
    book = _CHAPTER_TAIL.sub("", _PAGE_TAIL.sub("", label))
    return _MODULE_TAIL.sub("", _SECTION_TAIL.sub("", book))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _by_corpus(
    answered: Sequence[tuple[dict[str, Any], AskReply]], hits: Sequence[bool]
) -> dict[str, dict[str, float | int]]:
    """Answered and correct counts and the citation rate for each corpus a question's gold is in."""
    totals: dict[str, list[int]] = {}
    for (question, _), hit in zip(answered, hits, strict=True):
        counts = totals.setdefault(corpus_of(question["gold"][0]), [0, 0])
        counts[0] += 1
        counts[1] += int(hit)
    return {
        name: {"answered": n, "correct": ok, "rate": rate(ok, n)}
        for name, (n, ok) in sorted(totals.items())
    }


def _by_split(
    answered: Sequence[tuple[dict[str, Any], AskReply]], hits: Sequence[bool]
) -> dict[str, dict[str, float | int]]:
    """Citation counts per "split" (dev or held_out); questions without a split are skipped."""
    totals: dict[str, list[int]] = {}
    for (question, _), hit in zip(answered, hits, strict=True):
        name = question.get("split")
        if name is None:
            continue
        counts = totals.setdefault(name, [0, 0])
        counts[0] += 1
        counts[1] += int(hit)
    return {
        name: {"answered": n, "correct": ok, "rate": rate(ok, n)}
        for name, (n, ok) in sorted(totals.items())
    }


def load_eval_sets(
    datasets: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The in-scope, out-of-scope and corpus-gap questions: the guidance sets, then the textbook
    sets when their files exist. The two required files raise `FileNotFoundError` if absent."""

    def optional(name: str) -> list[dict[str, Any]]:
        path = datasets / name
        return _jsonl(path) if path.exists() else []

    inscope = _jsonl(datasets / "ask_inscope.jsonl") + optional("ask_textbook_inscope.jsonl")
    oos = _jsonl(datasets / "ask_oos.jsonl") + optional("ask_textbook_oos.jsonl")
    gap = optional("ask_corpus_gap.jsonl") + optional("ask_textbook_gap.jsonl")
    return inscope, oos, gap


def score(
    inscope: Sequence[tuple[dict[str, Any], AskReply | None]],
    oos: Sequence[AskReply | None],
    gap: Sequence[AskReply | None] = (),
) -> dict[str, object]:
    """Score the run. `gap` holds replies to questions the ingested books do not answer.

    A refusal is the right reply to those, so they are reported beside the targets and never
    count toward the citation, false-refusal or pass figures.
    """
    answered = [(q, r) for q, r in inscope if r is not None and not r.refused]
    hits = [any(label_matches(s, g) for s in r.sources for g in q["gold"]) for q, r in answered]
    correct = sum(hits)
    right_course = sum(
        any(course_of(s) == course_of(g) for s in r.sources for g in q["gold"]) for q, r in answered
    )
    false_refusals = sum(1 for _, r in inscope if r is not None and r.refused)
    refused = sum(1 for r in oos if r is not None and r.refused)
    citation_rate = rate(correct, len(answered))
    refusal_rate = rate(refused, len(oos))
    gap_refused = sum(1 for r in gap if r is not None and r.refused)
    false_rate = rate(false_refusals, len(inscope))
    return {
        "inscope": len(inscope),
        "out_of_scope": len(oos),
        "corpus_gap": len(gap),
        "unavailable": sum(1 for _, r in inscope if r is None)
        + sum(1 for r in (*oos, *gap) if r is None),
        "citation_correct_rate": citation_rate,
        "citation_by_corpus": _by_corpus(answered, hits),
        "citation_by_split": _by_split(answered, hits),
        "course_citation_correct_rate": rate(right_course, len(answered)),
        "oos_refusal_rate": refusal_rate,
        "corpus_gap_refusal_rate": rate(gap_refused, len(gap)),
        "false_refusal_rate": false_rate,
        "pass": citation_rate >= CITATION_TARGET
        and refusal_rate >= REFUSAL_TARGET
        and false_rate <= FALSE_REFUSAL_LIMIT,
    }


def question_details(
    inscope: Sequence[tuple[dict[str, Any], AskReply | None]],
) -> list[dict[str, object]]:
    """One row per in-scope question: what was asked, what was cited, and how each check went.

    The aggregate report says how many failed; this says which, so a corpus or retrieval change
    can be aimed at the failures. It holds questions and labels only, never an answer's text.
    """
    return [
        {
            "question": q["question"],
            "lang": q.get("lang", "hi"),
            "gold": q["gold"],
            "outcome": "unavailable" if r is None else "refused" if r.refused else "answered",
            "sources": [] if r is None else list(r.sources),
            "course_correct": r is not None
            and not r.refused
            and any(course_of(s) == course_of(g) for s in r.sources for g in q["gold"]),
        }
        for q, r in inscope
    ]


async def _ask(ask: AskAnviq, question: dict[str, Any], gate: asyncio.Semaphore) -> AskReply | None:
    async with gate:
        try:
            return await ask.answer(
                question["question"], question.get("lang", "hi"), grade=question.get("grade")
            )
        except AskUnavailableError:
            return None


async def _main(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    inscope, oos, gap = load_eval_sets(args.datasets)
    engine = create_async_engine(settings.database_url)
    gate = asyncio.Semaphore(args.concurrency)
    try:
        async with httpx.AsyncClient() as http:
            client = LLMClient(http, settings.anthropic_api_key.get_secret_value())
            retriever = HybridRetriever([postgres_bm25_search(engine)], settings.ask_min_score)
            ask = AskAnviq(
                client, retriever, fast_model=settings.model_fast, smart_model=settings.model_smart
            )
            in_replies = await asyncio.gather(*(_ask(ask, q, gate) for q in inscope))
            oos_replies = await asyncio.gather(*(_ask(ask, q, gate) for q in oos))
            gap_replies = await asyncio.gather(*(_ask(ask, q, gate) for q in gap))
    finally:
        await engine.dispose()
    report = score(
        list(zip(inscope, in_replies, strict=True)), list(oos_replies), list(gap_replies)
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.details is not None:
        details = question_details(list(zip(inscope, in_replies, strict=True)))
        args.details.parent.mkdir(parents=True, exist_ok=True)
        args.details.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--datasets", type=Path, default=Path("../eval/datasets"))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("../eval/results/citations.json"))
    parser.add_argument("--details", type=Path, default=None, help="per-question rows (optional)")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
