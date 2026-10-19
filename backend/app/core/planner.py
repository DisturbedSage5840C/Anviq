"""Planner: turn "tomorrow I teach X" into three questions to ask, with what children may answer.

Plan section 4.9: resolve the topic, gather the topic's known misconceptions, ask the model for
three questions, and check the result before it is spoken. The checks are ours, not the model's:
exactly three complete questions and no more than a minute of speech. One retry is allowed for a
bad or failed draft; after that the caller gets `PlanUnavailableError` and says so honestly.

The topic resolver, misconception source and writer are ports so the whole flow tests offline.
"""

from dataclasses import dataclass
from typing import Protocol

from app.content.copy import render
from app.core.speech_budget import PLAN_BUDGET_SECONDS, fits
from app.guardrails.pii import scrub

QUESTIONS_PER_PLAN = 3
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class Misconception:
    """A wrong answer children of this topic commonly give, and the thinking behind it."""

    child: str
    answer: str
    how: str


@dataclass(frozen=True)
class PlanQuestion:
    ask: str
    likely_answer: str
    guidance: str  # the "do" line: what the teacher does when a child answers like that


@dataclass(frozen=True)
class PlanRequest:
    text: str
    lang: str
    move_id: int
    week: str


@dataclass(frozen=True)
class Resolved:
    topic_id: str


@dataclass(frozen=True)
class Unsure:
    """The topic could not be pinned down; `prompt` is the question to put back to the teacher."""

    prompt: str


@dataclass(frozen=True)
class PlanBrief:
    """Everything the writer is given. Contains only scrubbed text."""

    request_text: str
    topic_id: str
    lang: str
    move_id: int
    week: str
    misconceptions: tuple[Misconception, ...]
    shorter: bool  # a previous draft ran past the speaking budget


@dataclass(frozen=True)
class AskBack:
    prompt: str


@dataclass(frozen=True)
class Planned:
    topic_id: str
    questions: tuple[PlanQuestion, ...]
    text: str  # what to say aloud: the questions, then the invitation to practise


class PlanWriterError(Exception):
    """The model call failed or returned something unreadable."""


class PlanUnavailableError(Exception):
    """No usable plan after the allowed attempts."""


class TopicResolver(Protocol):
    async def resolve(self, text: str, lang: str) -> Resolved | Unsure: ...


class MisconceptionSource(Protocol):
    async def for_topic(self, topic_id: str) -> tuple[Misconception, ...]: ...


class PlanWriter(Protocol):
    async def write(self, brief: PlanBrief) -> tuple[PlanQuestion, ...]: ...


def _is_complete(question: PlanQuestion) -> bool:
    return all(part.strip() for part in (question.ask, question.likely_answer, question.guidance))


def _well_formed(questions: tuple[PlanQuestion, ...]) -> bool:
    return len(questions) == QUESTIONS_PER_PLAN and all(_is_complete(q) for q in questions)


def render_plan(questions: tuple[PlanQuestion, ...], lang: str) -> str:
    answer_label = render("plan_label_answer", lang)
    do_label = render("plan_label_do", lang)
    numbered = [
        f"{number}) {q.ask}\n{answer_label}: {q.likely_answer}\n{do_label}: {q.guidance}"
        for number, q in enumerate(questions, start=1)
    ]
    return "\n\n".join([*numbered, render("plan_cta", lang)])


class Planner:
    def __init__(
        self, topics: TopicResolver, misconceptions: MisconceptionSource, writer: PlanWriter
    ) -> None:
        self._topics = topics
        self._misconceptions = misconceptions
        self._writer = writer

    async def plan(self, request: PlanRequest) -> AskBack | Planned:
        spoken = scrub(request.text)
        match = await self._topics.resolve(spoken, request.lang)
        if isinstance(match, Unsure):
            return AskBack(match.prompt)
        known = await self._misconceptions.for_topic(match.topic_id)
        return await self._write_within_budget(request, spoken, match.topic_id, known)

    async def _write_within_budget(
        self,
        request: PlanRequest,
        spoken: str,
        topic_id: str,
        known: tuple[Misconception, ...],
    ) -> Planned:
        shorter = False
        for _ in range(MAX_ATTEMPTS):
            brief = PlanBrief(
                spoken, topic_id, request.lang, request.move_id, request.week, known, shorter
            )
            try:
                questions = await self._writer.write(brief)
            except PlanWriterError:
                continue
            if not _well_formed(questions):
                continue
            text = render_plan(questions, request.lang)
            if fits(text, PLAN_BUDGET_SECONDS):
                return Planned(topic_id, questions, text)
            shorter = True
        raise PlanUnavailableError(f"no usable plan for {topic_id} after {MAX_ATTEMPTS} tries")
