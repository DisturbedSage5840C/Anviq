"""Are Ask Anviq's citations right, and does it refuse what it should? Plan section 8, rows 3-4.

Targets: cited section correct on >=95% of in-scope questions; >=95% of out-of-scope questions
refused; <=5% of in-scope questions wrongly refused. Needs the corpus ingested and a model key.

    ask_inscope.jsonl:  {"question": "...", "lang": "hi", "gold": ["NISHTHA FLN Course 9, §3.2"]}
    ask_oos.jsonl:      {"question": "...", "lang": "en"}

A cited label counts as correct when it equals a gold label or is a subsection of one (gold
"...§3" accepts "...§3.2"). The report also gives a looser course-level rate, which ignores the
module and section, because the gold's Module/§ numbering need not match the book's own headings.

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


def label_matches(cited: str, gold: str) -> bool:
    return cited == gold or cited.startswith(f"{gold}.")


def course_of(label: str) -> str:
    """A citation without its module and section: "NISHTHA FLN Course 9: Foundational Numeracy".

    Only a trailing ", §…" and then a trailing ", Module …" are removed, so commas inside a course
    title (Course 11) survive.
    """
    return _MODULE_TAIL.sub("", _SECTION_TAIL.sub("", label))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def score(
    inscope: Sequence[tuple[dict[str, Any], AskReply | None]], oos: Sequence[AskReply | None]
) -> dict[str, object]:
    answered = [(q, r) for q, r in inscope if r is not None and not r.refused]
    correct = sum(
        any(label_matches(s, g) for s in r.sources for g in q["gold"]) for q, r in answered
    )
    right_course = sum(
        any(course_of(s) == course_of(g) for s in r.sources for g in q["gold"]) for q, r in answered
    )
    false_refusals = sum(1 for _, r in inscope if r is not None and r.refused)
    refused = sum(1 for r in oos if r is not None and r.refused)
    citation_rate = rate(correct, len(answered))
    refusal_rate = rate(refused, len(oos))
    false_rate = rate(false_refusals, len(inscope))
    return {
        "inscope": len(inscope),
        "out_of_scope": len(oos),
        "unavailable": sum(1 for _, r in inscope if r is None) + sum(1 for r in oos if r is None),
        "citation_correct_rate": citation_rate,
        "course_citation_correct_rate": rate(right_course, len(answered)),
        "oos_refusal_rate": refusal_rate,
        "false_refusal_rate": false_rate,
        "pass": citation_rate >= CITATION_TARGET
        and refusal_rate >= REFUSAL_TARGET
        and false_rate <= FALSE_REFUSAL_LIMIT,
    }


async def _ask(ask: AskAnviq, question: dict[str, Any], gate: asyncio.Semaphore) -> AskReply | None:
    async with gate:
        try:
            return await ask.answer(question["question"], question.get("lang", "hi"))
        except AskUnavailableError:
            return None


async def _main(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    inscope = _jsonl(args.datasets / "ask_inscope.jsonl")
    oos = _jsonl(args.datasets / "ask_oos.jsonl")
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
    finally:
        await engine.dispose()
    report = score(list(zip(inscope, in_replies, strict=True)), list(oos_replies))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--datasets", type=Path, default=Path("../eval/datasets"))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("../eval/results/citations.json"))
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
