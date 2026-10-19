"""Which misconceptions belong to which topic, and problems that trigger them.

The topic ids here are the ones in `app/content/topics.toml`. The registry also serves as the
planner's source of "what children will say" for a topic, so the plan's likely answers are the
same answers the rehearsal children will give.
"""

import random
from functools import cache

from app.core.children.malrules import addition, comparison, place_value, subtraction, word_problem
from app.core.children.malrules.base import Malrule, MalruleResult
from app.core.children.problem import Kind, Problem
from app.core.planner import Misconception

ALL_RULES: tuple[Malrule, ...] = (
    *subtraction.RULES,
    *addition.RULES,
    *place_value.RULES,
    *comparison.RULES,
    *word_problem.RULES,
)
RULES_BY_ID = {rule.id: rule for rule in ALL_RULES}
MISCONCEPTIONS_PER_TOPIC = 3
MAX_DRAWS = 500

_KIND_BY_TOPIC = {
    subtraction.TOPIC_REGROUP: Kind.SUBTRACT,
    subtraction.TOPIC_ZERO: Kind.SUBTRACT,
    addition.TOPIC_REGROUP: Kind.ADD,
    addition.TOPIC_COUNT_ON: Kind.ADD,
    place_value.TOPIC: Kind.WRITE_NUMBER,
    comparison.TOPIC: Kind.COMPARE,
    word_problem.TOPIC: Kind.WORD_MORE_THAN,
}
TOPIC_IDS = tuple(_KIND_BY_TOPIC)
# Riya runs the main misconception, Meena a second one; see core/children/personas.py.
CHILDREN_FOR_MISCONCEPTIONS = ("Riya", "Meena", "Riya")


def rules_for_topic(topic_id: str) -> tuple[Malrule, ...]:
    return tuple(rule for rule in ALL_RULES if topic_id in rule.topic_ids)


def _draw(kind: Kind, rng: random.Random) -> Problem:
    match kind:
        case Kind.SUBTRACT | Kind.ADD:
            if kind is Kind.ADD and rng.random() < 0.5:
                return Problem(kind, rng.randint(1, 9), rng.randint(1, 9))
            a, b = rng.randint(10, 99), rng.randint(10, 99)
            return (
                Problem(kind, max(a, b), min(a, b))
                if kind is Kind.SUBTRACT
                else Problem(kind, a, b)
            )
        case Kind.WRITE_NUMBER:
            return Problem(kind, rng.randint(11, 99))
        case Kind.COMPARE:
            return Problem(kind, rng.randint(10, 99), rng.randint(10, 99))
        case Kind.WORD_MORE_THAN:
            a = rng.randint(6, 40)
            return Problem(kind, a, rng.randint(1, a - 1))
    raise AssertionError(kind)  # pragma: no cover


def problem_for(rule: Malrule, rng: random.Random) -> Problem:
    """A random problem on which `rule` makes its mistake."""
    kind = _KIND_BY_TOPIC[rule.topic_ids[0]]
    for _ in range(MAX_DRAWS):
        problem = _draw(kind, rng)
        if rule.applies(problem):
            return problem
    raise RuntimeError(f"no problem found for {rule.id}")  # pragma: no cover


def run_rule(rule: Malrule, problem: Problem) -> MalruleResult:
    return rule.run(problem)


@cache
def _example(rule_id: str) -> tuple[Problem, MalruleResult]:
    """A fixed example per rule, so the planner shows the same one every time."""
    rule = RULES_BY_ID[rule_id]
    problem = problem_for(rule, random.Random(rule_id))
    return problem, rule.run(problem)


class RegistryMisconceptions:
    """The planner's `MisconceptionSource`, backed by the executable malrules."""

    async def for_topic(self, topic_id: str) -> tuple[Misconception, ...]:
        rules = rules_for_topic(topic_id)[:MISCONCEPTIONS_PER_TOPIC]
        found = []
        for rule, child in zip(rules, CHILDREN_FOR_MISCONCEPTIONS, strict=False):
            problem, result = _example(rule.id)
            how = f"{problem.statement()}: {'; '.join(result.steps)}"
            found.append(Misconception(child, result.answer, how))
        return tuple(found)
