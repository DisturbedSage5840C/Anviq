import json
import random
from dataclasses import replace

import pytest

from app.core.children.personas import ChildState
from app.core.coach import CoachVerdict
from app.core.rehearsal import Exchange, RehearsalState, start
from app.core.rehearsal_codec import MAX_RAW_CHARS, MAX_TEXT_CHARS, dump, load

TOPIC = "NUM.G2.SUB.REGROUP"


def fresh() -> RehearsalState:
    return start(TOPIC, 2, "A", "hi", random.Random(7))


def played() -> RehearsalState:
    verdict = CoachVerdict(
        2,
        {"C1": True, "C2": False, "C3": True, "C4": False},
        {"C1": "तुमने कैसे किया"},
        "पूछिए: तुमने कैसे सोचा?",
        "अच्छा सवाल।",
    )
    return replace(
        fresh(),
        states={
            "riya": ChildState.EXPLAINING,
            "aman": ChildState.CONFUSED,
            "meena": ChildState.CONFUSED,
        },
        asked={"riya": 2, "aman": 0, "meena": 1},
        last_child_text="जवाब 28 है।",
        next_rotation=2,
        turns=3,
        good_turns=1,
        exchanges=(Exchange("तुमने कैसे किया", verdict),),
    )


def test_round_trips_a_fresh_rehearsal() -> None:
    state = fresh()

    assert load(dump(state)) == state


def test_round_trips_a_rehearsal_in_progress() -> None:
    state = played()

    assert load(dump(state)) == state


def test_dump_is_valid_json_text() -> None:
    assert isinstance(json.loads(dump(played())), dict)


def test_dump_scrubs_personal_data_from_what_the_teacher_said() -> None:
    state = played()
    said = replace(
        state.exchanges[0],
        teacher_text="Ravi ka number 9876543210 hai",
        verdict=replace(
            state.exchanges[0].verdict,
            evidence={"C1": "Ravi ne kaha 9876543210"},
        ),
    )

    stored = dump(replace(state, exchanges=(said,)))

    assert "9876543210" not in stored
    assert "Ravi" not in stored


def test_dump_keeps_the_ai_children_names() -> None:
    said = Exchange("Riya, aap kaise kiye?", played().exchanges[0].verdict)

    restored = load(dump(replace(played(), exchanges=(said,))))

    assert restored is not None
    assert restored.exchanges[0].teacher_text == "Riya, aap kaise kiye?"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[]",
        "null",
        "{}",
        '{"topic_id": "NUM.G2.SUB.REGROUP"}',
    ],
)
def test_load_returns_none_for_malformed_data(raw: str) -> None:
    assert load(raw) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("topic_id", "NO.SUCH.TOPIC"),
        ("primary_id", "no-such-rule"),
        ("secondary_id", "no-such-rule"),
        ("secondary_id", 5),
        ("lang", "fr"),
        ("week", "C"),
        ("move_id", 99),
        ("move_id", 2.0),
        ("last_child_text", "x" * (MAX_TEXT_CHARS + 1)),
        ("turns", -1),
        ("states", {"riya": "levitating", "aman": "confused", "meena": "confused"}),
        ("states", {"riya": "confused"}),
        ("problem", {"kind": "teleport", "a": 1, "b": 2}),
    ],
)
def test_load_rejects_values_the_engine_would_not_have_produced(field: str, value: object) -> None:
    data = json.loads(dump(fresh()))
    data[field] = value

    assert load(json.dumps(data)) is None


def test_load_rejects_an_oversized_history() -> None:
    data = json.loads(dump(played()))
    data["exchanges"] = data["exchanges"] * 50

    assert load(json.dumps(data)) is None


def _with_verdict(**changes: object) -> str:
    data = json.loads(dump(played()))
    data["exchanges"][0]["verdict"].update(changes)
    return json.dumps(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"criteria": {"C1": 1, "C2": 0, "C3": 1, "C4": 0}},
        {"criteria": {"C1": True}},
        {"criteria": {"C1": True, "C2": False, "C3": True, "C4": False, "C9": True}},
        {"evidence": {"C9": "not a criterion"}},
        {"move_id": 2.0},
        {"fell_back": "yes"},
        {"better_phrasing": "x" * (MAX_TEXT_CHARS + 1)},
        {"feedback": "x" * (MAX_TEXT_CHARS + 1)},
        {"evidence": {"C1": "x" * (MAX_TEXT_CHARS + 1)}},
    ],
)
def test_load_rejects_a_verdict_the_coach_could_not_have_produced(
    changes: dict[str, object],
) -> None:
    assert load(_with_verdict(**changes)) is None


def test_load_rejects_a_teacher_turn_longer_than_any_could_be() -> None:
    data = json.loads(dump(played()))
    data["exchanges"][0]["teacher_text"] = "x" * (MAX_TEXT_CHARS + 1)

    assert load(json.dumps(data)) is None


def test_dump_stays_loadable_however_much_the_model_wrote() -> None:
    long = "लंबा " * MAX_TEXT_CHARS
    verdict = replace(
        played().exchanges[0].verdict, better_phrasing=long, feedback=long, evidence={"C1": long}
    )
    state = replace(played(), last_child_text=long, exchanges=(Exchange(long, verdict),))

    restored = load(dump(state))

    assert restored is not None
    assert len(restored.exchanges[0].verdict.better_phrasing) <= MAX_TEXT_CHARS
    assert len(restored.last_child_text) <= MAX_TEXT_CHARS


def test_load_refuses_a_row_bigger_than_any_practice_could_be() -> None:
    assert load(dump(fresh()) + " " * MAX_RAW_CHARS) is None


def test_load_survives_json_nested_deeper_than_the_parser_allows() -> None:
    assert load("[" * (MAX_RAW_CHARS // 2)) is None
