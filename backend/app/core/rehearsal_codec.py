"""Rehearsal state as JSON text, so a practice can carry on across WhatsApp messages.

`dump` keeps only what the engine needs to resume and scrubs everything the teacher said. `load`
trusts nothing: a row that could not have come from `dump` yields None, and the caller ends the
practice instead of crashing on it.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

from app.core.children.personas import PERSONAS, ChildState
from app.core.children.problem import Kind, Problem
from app.core.children.registry import rules_for_topic
from app.core.coach import CoachVerdict
from app.core.rehearsal import MAX_TURNS, Exchange, RehearsalState
from app.core.rubric import MOVES, load_rubric
from app.guardrails.pii import scrub

LANGS = frozenset({"en", "hi"})
WEEKS = frozenset({"A", "B"})
MAX_TEXT_CHARS = 2000  # a spoken question, a child's line or a coach comment is far shorter
MAX_COUNT = 100
MAX_RAW_CHARS = 200_000  # MAX_TURNS exchanges of the longest texts is well under half of this
_CHILD_KEYS = frozenset(persona.key for persona in PERSONAS)


def dump(state: RehearsalState) -> str:
    problem = state.problem
    return json.dumps(
        {
            "topic_id": state.topic_id,
            "problem": {"kind": problem.kind.value, "a": problem.a, "b": problem.b},
            "primary_id": state.primary_id,
            "secondary_id": state.secondary_id,
            "move_id": state.move_id,
            "week": state.week,
            "lang": state.lang,
            "states": {key: value.value for key, value in state.states.items()},
            "asked": dict(state.asked),
            "last_child_text": _safe(state.last_child_text),
            "next_rotation": state.next_rotation,
            "turns": state.turns,
            "good_turns": state.good_turns,
            "exchanges": [_dump_exchange(e) for e in state.exchanges],
        },
        ensure_ascii=False,
    )


def _safe(text: str) -> str:
    """Scrubbed, then cut to what `load` accepts, so whatever the model wrote can be resumed."""
    return scrub(text)[:MAX_TEXT_CHARS]


def _dump_exchange(exchange: Exchange) -> dict[str, Any]:
    verdict = exchange.verdict
    return {
        "teacher_text": _safe(exchange.teacher_text),
        "verdict": {
            "move_id": verdict.move_id,
            "criteria": dict(verdict.criteria),
            "evidence": {cid: _safe(quote) for cid, quote in verdict.evidence.items()},
            "better_phrasing": _safe(verdict.better_phrasing),
            "feedback": _safe(verdict.feedback),
            "fell_back": verdict.fell_back,
        },
    }


def load(raw: str) -> RehearsalState | None:
    """The saved state, or None if `raw` is not exactly what `dump` would have written."""
    if len(raw) > MAX_RAW_CHARS:
        return None
    try:
        return _build(json.loads(raw))
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return None


def _build(data: Any) -> RehearsalState:
    if not isinstance(data, dict):
        raise ValueError("not an object")
    topic_id = _text(data["topic_id"])
    primary_id = _text(data["primary_id"])
    secondary_id = None if data["secondary_id"] is None else _text(data["secondary_id"])
    rule_ids = {rule.id for rule in rules_for_topic(topic_id)}
    if primary_id not in rule_ids or (secondary_id is not None and secondary_id not in rule_ids):
        raise ValueError("unknown topic or misconception")
    return RehearsalState(
        topic_id=topic_id,
        problem=_problem(data["problem"]),
        primary_id=primary_id,
        secondary_id=secondary_id,
        move_id=_move(data["move_id"]),
        week=_choice(data["week"], WEEKS),
        lang=_choice(data["lang"], LANGS),
        states=_per_child(data["states"], lambda v: ChildState(_text(v))),
        asked=_per_child(data["asked"], _count),
        last_child_text=_text(data["last_child_text"]),
        next_rotation=_count(data["next_rotation"]),
        turns=_count(data["turns"]),
        good_turns=_count(data["good_turns"]),
        exchanges=_exchanges(data["exchanges"]),
    )


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT_CHARS:
        raise ValueError("not a short text")
    return value


def _count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ValueError("not a small count")
    return value


def _choice(value: Any, allowed: Any) -> Any:
    if isinstance(value, bool) or value not in allowed:
        raise ValueError("not an allowed value")
    return value


def _move(value: Any) -> int:
    """A coaching move id: a real int, since `2.0 in range(1, 7)` is True."""
    if type(value) is not int:
        raise ValueError("not a move id")
    return int(_choice(value, MOVES))


def _problem(data: Any) -> Problem:
    return Problem(Kind(_text(data["kind"])), _count(data["a"]), _count(data["b"]))


def _per_child(data: Any, convert: Callable[[Any], Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != _CHILD_KEYS:
        raise ValueError("not one entry per child")
    return {key: convert(value) for key, value in data.items()}


def _exchanges(data: Any) -> tuple[Exchange, ...]:
    if not isinstance(data, list) or len(data) > MAX_TURNS:
        raise ValueError("too many exchanges")
    return tuple(Exchange(_text(item["teacher_text"]), _verdict(item["verdict"])) for item in data)


def _verdict(data: Any) -> CoachVerdict:
    move_id = _move(data["move_id"])
    criteria: Mapping[str, Any] = data["criteria"]
    evidence = data["evidence"]
    judged = set(load_rubric(move_id).criterion_ids)
    if (
        not isinstance(criteria, dict)
        or set(criteria) != judged
        or not all(type(met) is bool for met in criteria.values())
    ):
        raise ValueError("bad criteria")
    if not isinstance(evidence, dict) or not set(evidence) <= judged:
        raise ValueError("bad evidence")
    if type(data["fell_back"]) is not bool:
        raise ValueError("bad fell_back")
    return CoachVerdict(
        move_id,
        dict(criteria),
        {cid: _text(quote) for cid, quote in evidence.items()},
        _text(data["better_phrasing"]),
        _text(data["feedback"]),
        fell_back=data["fell_back"],
    )
