"""Rehearsal: the teacher practises a question on three AI children while the coach listens.

Plan section 3.3 B. Each turn the teacher speaks to one child; that child answers in character
and the coach scores the turn silently. The children's wrong answers come from executable
malrules, never from the model. When the teacher draws a child out well (C1 and C2 met), that
child moves confused -> explaining -> self-correcting, which is the reward that keeps teachers
practising.

To keep the reply fast, the child's line for "stay as they are" and for "move on a step" is
written at the same time as the coach scores the turn, and the right one is used. A turn costs
one extra cheap call and takes no longer than the coach alone.
"""

import asyncio
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Protocol

from app.content.copy import render
from app.core.children.malrules.base import Malrule
from app.core.children.malrules.steps import correct_steps
from app.core.children.personas import AMAN, MEENA, PERSONAS, ChildState, Persona, addressed_child
from app.core.children.problem import Problem
from app.core.children.registry import RULES_BY_ID, problem_for, rules_for_topic
from app.core.children.verbalizer import ChildBrief, ChildVoice, hesitation, speak_checked
from app.core.coach import CoachRequest, CoachUnavailableError, CoachVerdict, nudge_text

MAX_TURNS = 6
GOOD_TURNS_TO_FINISH = 3
GOOD_AT = 2  # criteria met for a turn to count as good
_STOP_WORDS = frozenset({"बस", "bas", "enough", "done", "finish", "ख़त्म", "खत्म"})
_TOKEN = re.compile(r"[\wऀ-ॿ]+")
_MAX_STOP_TOKENS = 3
_PLAN_DRAWS = 200


class Scorer(Protocol):
    async def score(self, request: CoachRequest) -> CoachVerdict: ...


@dataclass(frozen=True)
class Exchange:
    """One scored teacher turn, kept for the closing summary."""

    teacher_text: str
    verdict: CoachVerdict


@dataclass(frozen=True)
class RehearsalState:
    topic_id: str
    problem: Problem
    primary_id: str
    secondary_id: str | None
    move_id: int
    week: str
    lang: str
    states: Mapping[str, ChildState]
    asked: Mapping[str, int]  # times each child has been spoken to
    last_child_text: str
    next_rotation: int
    turns: int
    good_turns: int
    exchanges: tuple[Exchange, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "states", MappingProxyType(dict(self.states)))
        object.__setattr__(self, "asked", MappingProxyType(dict(self.asked)))


@dataclass(frozen=True)
class TurnOutcome:
    state: RehearsalState
    child: Persona | None  # None when the teacher ended the practice
    child_text: str
    malrule_id: str | None  # the misconception the child's answer came from, if any
    verdict: CoachVerdict | None  # None when the coach was unavailable or the teacher stopped
    nudge: str | None
    finished: bool
    summary: str | None


def wants_to_stop(text: str) -> bool:
    tokens = _TOKEN.findall(text.casefold())
    return 0 < len(tokens) <= _MAX_STOP_TOKENS and any(t in _STOP_WORDS for t in tokens)


def start(topic_id: str, move_id: int, week: str, lang: str, rng: random.Random) -> RehearsalState:
    rules = rules_for_topic(topic_id)
    if not rules:
        raise ValueError(f"no misconceptions known for topic {topic_id}")
    primary = rules[0]
    problem, secondary = _pick_problem(primary, rules[1:], rng)
    return RehearsalState(
        topic_id=topic_id,
        problem=problem,
        primary_id=primary.id,
        secondary_id=secondary.id if secondary else None,
        move_id=move_id,
        week=week,
        lang=lang,
        states=dict.fromkeys((p.key for p in PERSONAS), ChildState.CONFUSED),
        asked=dict.fromkeys((p.key for p in PERSONAS), 0),
        last_child_text="",
        next_rotation=0,
        turns=0,
        good_turns=0,
        exchanges=(),
    )


def _pick_problem(
    primary: Malrule, others: tuple[Malrule, ...], rng: random.Random
) -> tuple[Problem, Malrule | None]:
    """A problem the main misconception fires on, and a second misconception if one fits too."""
    problem = problem_for(primary, rng)
    for _ in range(_PLAN_DRAWS):
        for other in others:
            if other.applies(problem):
                return problem, other
        problem = problem_for(primary, rng)
    return problem, None


@dataclass(frozen=True)
class _Plan:
    """What a child will say, decided before any model is asked."""

    persona: Persona
    brief: ChildBrief | None  # None: a fixed line, no model needed
    fixed: str
    malrule_id: str | None


def _rule_for(state: RehearsalState, persona: Persona) -> Malrule:
    if persona is MEENA and state.secondary_id:
        return RULES_BY_ID[state.secondary_id]
    return RULES_BY_ID[state.primary_id]


def _plan_child(
    state: RehearsalState, persona: Persona, child_state: ChildState, teacher_text: str
) -> _Plan:
    problem = state.problem
    correct = problem.correct_answer()
    if persona is MEENA and child_state is ChildState.CONFUSED and state.asked[persona.key] == 0:
        return _Plan(persona, None, hesitation(state.lang), None)
    if persona is AMAN:
        explains = child_state is not ChildState.CONFUSED
        steps = correct_steps(problem) if explains else ()
        return _Plan(
            persona, _brief(state, persona, correct, steps, True, explains, teacher_text), "", None
        )
    result = _rule_for(state, persona).run(problem)
    if child_state is ChildState.SELF_CORRECTING:
        brief = _brief(state, persona, correct, correct_steps(problem), True, True, teacher_text)
        return _Plan(persona, brief, "", None)
    explains = child_state is ChildState.EXPLAINING
    steps = result.steps if explains else ()
    brief = _brief(state, persona, result.answer, steps, False, explains, teacher_text)
    return _Plan(persona, brief, "", result.misconception_id)


def _brief(
    state: RehearsalState,
    persona: Persona,
    answer: str,
    steps: tuple[str, ...],
    knows_correct: bool,
    explains: bool,
    teacher_text: str,
) -> ChildBrief:
    return ChildBrief(
        persona=persona,
        lang=state.lang,
        problem=state.problem.statement(),
        answer=answer,
        steps=steps,
        correct=state.problem.correct_answer(),
        knows_correct=knows_correct,
        explains=explains,
        teacher_text=teacher_text,
    )


def _who_answers(state: RehearsalState, teacher_text: str) -> tuple[Persona, int]:
    named = addressed_child(teacher_text)
    if named is not None:
        return named, state.next_rotation
    return PERSONAS[state.next_rotation % len(PERSONAS)], state.next_rotation + 1


async def _line(voice: ChildVoice, plan: _Plan) -> str:
    return plan.fixed if plan.brief is None else await speak_checked(voice, plan.brief)


class RehearsalEngine:
    def __init__(self, voice: ChildVoice, coach: Scorer) -> None:
        self._voice = voice
        self._coach = coach

    async def take_turn(self, state: RehearsalState, teacher_text: str) -> TurnOutcome:
        if wants_to_stop(teacher_text):
            return _ended(state)
        persona, rotation = _who_answers(state, teacher_text)
        current = state.states[persona.key]
        stay = _plan_child(state, persona, current, teacher_text)
        can_advance = stay.brief is not None and current.next() != current
        move = _plan_child(state, persona, current.next(), teacher_text) if can_advance else None
        request = CoachRequest(
            state.move_id, state.week, state.lang, persona.name, state.last_child_text,
            teacher_text, current,
        )  # fmt: skip
        verdict, stay_line, move_line = await asyncio.gather(
            self._safe_score(request),
            _line(self._voice, stay),
            _line(self._voice, move) if move is not None else _none(),
        )
        advances = verdict is not None and verdict.advances_child and move_line is not None
        if advances and move is not None and move_line is not None:
            chosen, line = move, move_line
        else:
            chosen, line = stay, stay_line
        return _after(state, persona, rotation, chosen, line, teacher_text, verdict, advances)

    async def _safe_score(self, request: CoachRequest) -> CoachVerdict | None:
        try:
            return await self._coach.score(request)
        except CoachUnavailableError:
            return None


async def _none() -> None:
    return None


def _after(
    state: RehearsalState,
    persona: Persona,
    rotation: int,
    chosen: _Plan,
    line: str,
    teacher_text: str,
    verdict: CoachVerdict | None,
    advances: bool,
) -> TurnOutcome:
    states = dict(state.states)
    if advances:
        states[persona.key] = state.states[persona.key].next()
    asked = {**state.asked, persona.key: state.asked[persona.key] + 1}
    good = verdict is not None and verdict.met_count >= GOOD_AT
    exchanges = state.exchanges + ((Exchange(teacher_text, verdict),) if verdict else ())
    new = replace(
        state,
        states=states,
        asked=asked,
        last_child_text=line,
        next_rotation=rotation,
        turns=state.turns + 1,
        good_turns=state.good_turns + (1 if good else 0),
        exchanges=exchanges,
    )
    finished = new.turns >= MAX_TURNS or new.good_turns >= GOOD_TURNS_TO_FINISH
    return TurnOutcome(
        state=new,
        child=persona,
        child_text=line,
        malrule_id=chosen.malrule_id,
        verdict=verdict,
        nudge=nudge_text(verdict, state.lang) if verdict else None,
        finished=finished,
        summary=summarise(new) if finished else None,
    )


def _ended(state: RehearsalState) -> TurnOutcome:
    return TurnOutcome(state, None, "", None, None, None, True, summarise(state))


def summarise(state: RehearsalState) -> str:
    """The best question of the session, plus one line worth remembering."""
    if not state.exchanges:
        return render("rehearsal_summary_none", state.lang)
    best = max(state.exchanges, key=lambda e: e.verdict.met_count)  # first wins ties
    parts = [f"{render('rehearsal_summary_best', state.lang)}: {best.teacher_text}"]
    phrasing = next(
        (e.verdict.better_phrasing for e in state.exchanges if e.verdict.better_phrasing), ""
    )
    if phrasing:
        parts.append(f"{render('rehearsal_summary_phrasing', state.lang)}: {phrasing}")
    return "\n".join(parts)
