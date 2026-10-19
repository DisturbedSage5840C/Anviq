"""The teacher's daily loop beyond rehearsal: Plan, Reflect, Ask and the Day-14 Mirror.

The router decides *that* a teacher asked for one of these; this module does the work. The model
writers, move lookup and mirror storage are ports, so the whole flow tests offline and a
deployment without a model key can still run with the loop switched off.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

from app.content.copy import render
from app.core.ask.answer import AskReply, AskUnavailableError
from app.core.mirror import MirrorTurn, compare, render_mirror
from app.core.planner import AskBack, Planned, PlanRequest, PlanUnavailableError
from app.core.reflect import Reflected, ReflectRequest, ReflectUnavailableError
from app.core.router import Phase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Position:
    """Where the teacher is in the six-move programme."""

    move_id: int
    week: str  # "A" or "B"


@dataclass(frozen=True)
class LoopReply:
    text: str
    # Set when the teacher has been asked something back and must answer in the same prompt.
    stay_in: Phase | None = None


class Plans(Protocol):
    async def plan(self, request: PlanRequest) -> AskBack | Planned: ...


class Reflections(Protocol):
    async def reflect(self, request: ReflectRequest) -> Reflected: ...


class Positions(Protocol):
    async def current(self, teacher: bytes) -> Position: ...


class Mirrors(Protocol):
    async def comparable(self, teacher: bytes) -> tuple[MirrorTurn, MirrorTurn] | None:
        """The Day 1 and latest turns, once the cycle is due and has two sessions; else None."""
        ...

    async def complete(self, teacher: bytes) -> None:
        """Record the comparison as done and unlock the next move."""
        ...


class Answers(Protocol):
    async def answer(self, question: str, lang: str) -> AskReply: ...


class DailyLoop(Protocol):
    async def plan(self, teacher: bytes, lang: str, text: str) -> LoopReply: ...

    async def reflect(self, teacher: bytes, lang: str, text: str) -> LoopReply: ...

    async def mirror(self, teacher: bytes, lang: str) -> LoopReply: ...

    async def ask(self, teacher: bytes, lang: str, text: str) -> LoopReply: ...


class PipelineDailyLoop:
    def __init__(
        self,
        planner: Plans,
        reflector: Reflections,
        positions: Positions,
        mirrors: Mirrors,
        asker: Answers | None = None,
    ) -> None:
        self._planner = planner
        self._reflector = reflector
        self._positions = positions
        self._mirrors = mirrors
        self._asker = asker

    async def plan(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        position = await self._positions.current(teacher)
        try:
            outcome = await self._planner.plan(
                PlanRequest(text, lang, position.move_id, position.week)
            )
        except PlanUnavailableError:
            return LoopReply(render("plan_unavailable", lang))
        if isinstance(outcome, AskBack):
            return LoopReply(outcome.prompt, stay_in=Phase.PLAN_TOPIC)
        return LoopReply(outcome.text)

    async def reflect(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        position = await self._positions.current(teacher)
        try:
            outcome = await self._reflector.reflect(ReflectRequest(text, lang, position.move_id))
        except ReflectUnavailableError:
            return LoopReply(render("reflect_unavailable", lang))
        return LoopReply(outcome.text)

    async def mirror(self, teacher: bytes, lang: str) -> LoopReply:
        pair = await self._mirrors.comparable(teacher)
        if pair is None:
            return LoopReply(render("mirror_not_ready", lang))
        first, latest = pair
        shown = render_mirror(compare(first, latest), lang)
        await self._mirrors.complete(teacher)
        return LoopReply(f"{shown}\n\n{render('mirror_next_move', lang)}")

    async def ask(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        if self._asker is None:
            return LoopReply(render("ask_unavailable", lang))
        try:
            reply = await self._asker.answer(text, lang)
        except AskUnavailableError as exc:
            logger.error("ask unavailable: %s", type(exc).__name__)
            return LoopReply(render("ask_unavailable", lang))
        return LoopReply(reply.text)
