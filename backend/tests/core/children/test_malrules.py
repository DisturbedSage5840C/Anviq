import random
from collections.abc import Iterator

import pytest

from app.core.children.problem import Kind, Problem
from app.core.children.registry import (
    ALL_RULES,
    RULES_BY_ID,
    TOPIC_IDS,
    RegistryMisconceptions,
    problem_for,
    rules_for_topic,
)

# Worked examples straight from plan section 4.6.
EXAMPLES = [
    ("SUB.SMALLER_FROM_LARGER", Problem(Kind.SUBTRACT, 52, 17), "45", "35"),
    ("SUB.BORROW_NO_DECREMENT", Problem(Kind.SUBTRACT, 63, 29), "44", "34"),
    ("SUB.ZERO_MINUS_N_IS_N", Problem(Kind.SUBTRACT, 40, 17), "37", "23"),
    ("SUB.N_MINUS_ZERO_IS_ZERO", Problem(Kind.SUBTRACT, 58, 20), "30", "38"),
    ("SUB.ALWAYS_LEFT_TO_RIGHT", Problem(Kind.SUBTRACT, 52, 17), "53", "35"),
    ("ADD.NO_CARRY", Problem(Kind.ADD, 47, 38), "75", "85"),
    ("ADD.CARRY_WRITE_BOTH", Problem(Kind.ADD, 47, 38), "715", "85"),
    ("ADD.COUNT_ON_INCLUDES_START", Problem(Kind.ADD, 5, 3), "7", "8"),
    ("PV.CONCAT_WRITE", Problem(Kind.WRITE_NUMBER, 52), "502", "52"),
    ("PV.DIGIT_REVERSAL", Problem(Kind.WRITE_NUMBER, 21), "12", "21"),
    ("CMP.ONES_DIGIT_DECIDES", Problem(Kind.COMPARE, 39, 41), "39", "41"),
    ("WP.KEYWORD_MORE_MEANS_ADD", Problem(Kind.WORD_MORE_THAN, 12, 5), "17", "7"),
]


def test_there_are_twelve_unique_rules():
    assert len(ALL_RULES) == 12
    assert len(RULES_BY_ID) == 12


@pytest.mark.parametrize(("rule_id", "problem", "wrong", "right"), EXAMPLES)
def test_rule_reproduces_the_plan_example(rule_id: str, problem: Problem, wrong: str, right: str):
    result = RULES_BY_ID[rule_id].run(problem)
    assert (result.answer, result.correct_answer, result.misconception_id) == (
        wrong,
        right,
        rule_id,
    )
    assert result.steps


def _grid(rule_id: str) -> Iterator[Problem]:
    kind = {
        "SUB": Kind.SUBTRACT,
        "ADD": Kind.ADD,
        "PV": Kind.WRITE_NUMBER,
        "CMP": Kind.COMPARE,
        "WP": Kind.WORD_MORE_THAN,
    }[rule_id.split(".")[0]]
    for a in range(1, 100):
        for b in range(0, 100):
            yield Problem(kind, a, b)


@pytest.mark.parametrize("rule_id", sorted(RULES_BY_ID))
def test_wherever_a_rule_applies_its_answer_is_wrong(rule_id: str):
    rule = RULES_BY_ID[rule_id]
    applicable = [p for p in _grid(rule_id) if rule.applies(p)]
    assert len(applicable) >= 20  # enough distinct problems to test against
    for problem in applicable:
        result = rule.run(problem)
        assert result.answer != problem.correct_answer(), (rule_id, problem)
        assert result.answer.isdigit()
        assert not result.answer.startswith("0")


@pytest.mark.parametrize("rule_id", sorted(RULES_BY_ID))
def test_generated_problems_always_trigger_the_rule(rule_id: str):
    rule = RULES_BY_ID[rule_id]
    rng = random.Random(7)
    for _ in range(25):
        assert rule.applies(problem_for(rule, rng))


def test_running_a_rule_where_it_does_not_apply_is_an_error():
    with pytest.raises(ValueError, match="does not apply"):
        RULES_BY_ID["SUB.SMALLER_FROM_LARGER"].run(Problem(Kind.SUBTRACT, 58, 21))


def test_every_rule_has_a_topic_grade_source_and_summary():
    for rule in ALL_RULES:
        assert rule.topic_ids and rule.grades and rule.source and rule.summary
        assert rule.topic_ids[0] in TOPIC_IDS


def test_each_topic_has_at_least_one_rule():
    assert all(rules_for_topic(topic) for topic in TOPIC_IDS)


async def test_planner_misconceptions_come_from_the_executable_rules():
    found = await RegistryMisconceptions().for_topic("NUM.G2.SUB.REGROUP")
    assert 1 <= len(found) <= 3
    assert found[0].child == "Riya"
    assert all(m.answer.isdigit() and m.how for m in found)
    again = await RegistryMisconceptions().for_topic("NUM.G2.SUB.REGROUP")
    assert found == again


async def test_unknown_topic_has_no_misconceptions():
    assert await RegistryMisconceptions().for_topic("NUM.NOPE") == ()
