"""Which misconceptions belong to which topic, and problems that trigger them.

The topic ids here are the ones in `app/content/topics.toml`. The registry also serves as the
planner's source of "what children will say" for a topic, so the plan's likely answers are the
same answers the rehearsal children will give.
"""

import random
from functools import cache

from app.core.children.malrules import (
    addition,
    area,
    comparison,
    division,
    fraction_add,
    large_number,
    lexicon,
    literacy_decoding,
    literacy_spelling,
    multiplication,
    place_value,
    subtraction,
    word_problem,
)
from app.core.children.malrules.base import Malrule, MalruleResult
from app.core.children.problem import Kind, Problem
from app.core.planner import Misconception

ALL_RULES: tuple[Malrule, ...] = (
    *subtraction.RULES,
    *addition.RULES,
    *place_value.RULES,
    *comparison.RULES,
    *word_problem.RULES,
    *multiplication.RULES,
    *division.RULES,
    *fraction_add.RULES,
    *area.RULES,
    *large_number.RULES,
    *literacy_decoding.RULES,
    *literacy_spelling.RULES,
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
    multiplication.TOPIC: Kind.MULTIPLY,
    division.TOPIC: Kind.DIVIDE,
    fraction_add.TOPIC: Kind.ADD_FRACTIONS,
    area.TOPIC: Kind.AREA,
    large_number.TOPIC: Kind.WRITE_LARGE_NUMBER,
    literacy_decoding.TOPIC_LETTERS: Kind.READ_WORD,
    literacy_decoding.TOPIC_BLEND: Kind.READ_WORD,
    literacy_decoding.TOPIC_SIGHT: Kind.READ_WORD,
    literacy_spelling.TOPIC_SOUND: Kind.SPELL_WORD,
    literacy_spelling.TOPIC_PLURAL: Kind.SPELL_WORD,
    literacy_spelling.TOPIC_SUFFIX: Kind.SPELL_WORD,
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
        case Kind.MULTIPLY:
            if rng.random() < 0.5:
                return Problem(kind, rng.randint(10, 99), rng.randint(2, 9))
            return Problem(kind, rng.randint(10, 99), rng.randint(10, 99))
        case Kind.DIVIDE:
            divisor = rng.randint(2, 9)
            quotient = rng.randint(1, 9) * 100 + rng.randint(1, 9)  # a zero in the tens place
            return Problem(kind, quotient * divisor, divisor)
        case Kind.ADD_FRACTIONS:
            b = rng.randint(2, 9)
            d = rng.choice([n for n in range(2, 10) if n != b])
            return Problem(kind, rng.randint(1, b - 1), b, rng.randint(1, d - 1), d)
        case Kind.AREA:
            return Problem(kind, rng.randint(3, 30), rng.randint(2, 20))
        case Kind.WRITE_LARGE_NUMBER:
            return Problem(kind, rng.randint(1, 999) * 1000 + rng.randint(1, 99))
        case Kind.READ_WORD:
            return Problem(kind, text=rng.choice(lexicon.READ_WORDS))
        case Kind.SPELL_WORD:
            return Problem(kind, text=rng.choice(lexicon.SPELL_WORDS))
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
