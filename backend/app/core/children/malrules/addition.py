"""Addition misconceptions (BUGGY; early-number research on counting on)."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem, digits

TOPIC_REGROUP = "NUM.G2.ADD.REGROUP"
TOPIC_COUNT_ON = "NUM.G1.ADD.SINGLE"


def _carry_case(p: Problem) -> bool:
    if p.kind is not Kind.ADD or not (10 <= p.a <= 99 and 10 <= p.b <= 99):
        return False
    (ta, oa), (tb, ob) = digits(p.a), digits(p.b)
    return oa + ob >= 10 and ta + tb <= 8


def _no_carry(p: Problem) -> tuple[str, tuple[str, ...]]:
    (ta, oa), (tb, ob) = digits(p.a), digits(p.b)
    ones, tens = oa + ob - 10, ta + tb
    steps = (
        f"ones: {oa}+{ob}={oa + ob}, write {ones} and leave the ten out",
        f"tens: {ta}+{tb}={tens}",
    )
    return f"{tens}{ones}", steps


def _write_both(p: Problem) -> tuple[str, tuple[str, ...]]:
    (ta, oa), (tb, ob) = digits(p.a), digits(p.b)
    steps = (
        f"ones: {oa}+{ob}={oa + ob}, write all of {oa + ob} in the ones place",
        f"tens: {ta}+{tb}={ta + tb}",
    )
    return f"{ta + tb}{oa + ob}", steps


def _count_on_case(p: Problem) -> bool:
    return p.kind is Kind.ADD and 1 <= p.a <= 9 and 1 <= p.b <= 9


def _count_on(p: Problem) -> tuple[str, tuple[str, ...]]:
    total = p.a + p.b - 1
    steps = (
        f"count on: say {p.a}, then count {p.b} numbers beginning with {p.a} itself",
        f"stops at {total}",
    )
    return str(total), steps


NO_CARRY = Malrule(
    "ADD.NO_CARRY", (TOPIC_REGROUP,), (2, 3), "Brown & Burton (1978) BUGGY",
    "Drops the carried ten when the ones add up to ten or more.",
    _carry_case, _no_carry,
)  # fmt: skip
CARRY_WRITE_BOTH = Malrule(
    "ADD.CARRY_WRITE_BOTH", (TOPIC_REGROUP,), (2, 3), "Brown & Burton (1978) BUGGY",
    "Writes the whole ones total (like 15) in the ones place instead of carrying.",
    _carry_case, _write_both,
)  # fmt: skip
COUNT_ON_INCLUDES_START = Malrule(
    "ADD.COUNT_ON_INCLUDES_START", (TOPIC_COUNT_ON,), (1,), "Early number-sense research",
    "Counts on but counts the starting number again, so ends one short.",
    _count_on_case, _count_on,
)  # fmt: skip

RULES = (NO_CARRY, CARRY_WRITE_BOTH, COUNT_ON_INCLUDES_START)
