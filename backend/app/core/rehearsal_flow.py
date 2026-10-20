"""The practice with three AI children, one WhatsApp message at a time.

The router decides *that* the teacher is practising; this module runs a turn. The engine does the
teaching logic and the codec turns its state into text, so the flow only chooses what the teacher
reads and what is saved. It never raises: whatever goes wrong, the teacher gets a sentence.
"""

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.content.copy import render
from app.core.children.personas import Persona
from app.core.daily_loop import Positions
from app.core.rehearsal import RehearsalEngine, RehearsalState, TurnOutcome, start
from app.core.rehearsal_codec import dump, load
from app.core.rehearsal_log import LoggedTurn
from app.core.self_rating import rating_prompt
from app.guardrails.pii import scrub

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RehearsalReply:
    text: str
    # What to keep for the next message; None clears the practice.
    rehearsal_json: str | None
    # True once the practice is over and the teacher is back at the menu.
    finished: bool
    # The question the coach scored this turn, for the router to log once the turn stands.
    scored: LoggedTurn | None = None


class Rehearsals(Protocol):
    async def begin(self, teacher: bytes, lang: str, topic_id: str | None) -> RehearsalReply: ...

    async def turn(
        self, teacher: bytes, lang: str, text: str, saved: str | None
    ) -> RehearsalReply: ...


def _over(text: str) -> RehearsalReply:
    return RehearsalReply(text, None, True)


class RehearsalFlow:
    def __init__(
        self,
        engine: RehearsalEngine,
        positions: Positions,
        rng_factory: Callable[[], random.Random] = random.Random,
    ) -> None:
        self._engine = engine
        self._positions = positions
        self._rng_factory = rng_factory

    async def begin(self, teacher: bytes, lang: str, topic_id: str | None) -> RehearsalReply:
        if topic_id is None:
            return _over(render("rehearsal_needs_plan", lang))
        try:
            position = await self._positions.current(teacher)
            state = start(topic_id, position.move_id, position.week, lang, self._rng_factory())
        except Exception as exc:  # the teacher is told; the type is the only safe detail to log
            logger.error("rehearsal could not start: %s", type(exc).__name__)
            return _over(render("rehearsal_unavailable", lang))
        board = render("rehearsal_problem", lang).format(problem=state.problem.statement())
        return RehearsalReply(f"{render('rehearsal_started', lang)}\n{board}", dump(state), False)

    async def turn(self, teacher: bytes, lang: str, text: str, saved: str | None) -> RehearsalReply:
        state = None if saved is None else load(saved)
        if state is None:
            if saved is not None:
                logger.warning("saved rehearsal is unreadable; ending the practice")
            return _over(render("rehearsal_unavailable", lang))
        try:
            # Like Plan, Reflect and Ask: no phone number or pupil name leaves for the model.
            outcome = await self._engine.take_turn(state, scrub(text))
        except Exception as exc:  # keep the practice: the teacher can say it again
            logger.error("rehearsal turn failed: %s", type(exc).__name__)
            return RehearsalReply(render("rehearsal_turn_failed", state.lang), saved, False)
        return RehearsalReply(
            _compose(outcome, state.lang),
            None if outcome.finished else dump(outcome.state),
            outcome.finished,
            _logged(state, outcome),
        )


def _logged(before: RehearsalState, outcome: TurnOutcome) -> LoggedTurn | None:
    """The scored question of this turn; a rating reply, an exit or a coach outage has none."""
    if outcome.verdict is None or not outcome.state.exchanges:
        return None
    return LoggedTurn(
        move_id=before.move_id,
        topic_id=before.topic_id,
        week=before.week,
        teacher_text=outcome.state.exchanges[-1].teacher_text,
        criteria=outcome.verdict.criteria,
        child_name=outcome.child.name if outcome.child else None,
        malrule_id=outcome.malrule_id,
    )


def _compose(outcome: TurnOutcome, lang: str) -> str:
    parts: list[str] = []
    if outcome.child is not None:
        parts.append(f"{_name(outcome.child, lang)}: {outcome.child_text}")
    if outcome.ask_rating:
        parts.append(rating_prompt(lang))
    elif outcome.nudge:
        parts.append(outcome.nudge)
    elif outcome.verdict is None and outcome.child is not None and not outcome.finished:
        parts.append(render("rehearsal_coach_unavailable", lang))
    if outcome.summary:
        parts.append(outcome.summary)
    return "\n\n".join(parts)


def _name(child: Persona, lang: str) -> str:
    return child.name_hi if lang == "hi" else child.name
