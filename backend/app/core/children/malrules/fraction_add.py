"""Class 5 fraction misconceptions: adding fractions that have different denominators."""

from fractions import Fraction

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem

TOPIC = "NUM.G5.FRAC.ADD_UNLIKE"
SOURCE = (
    "Fraction-addition error literature "
    "(treating numerator and denominator as separate whole numbers)"
)


def _proper_unlike(p: Problem) -> bool:
    return p.kind is Kind.ADD_FRACTIONS and 1 <= p.a < p.b and 1 <= p.c < p.d and p.b != p.d


def _differs(p: Problem, wrong_numerator: int, wrong_denominator: int) -> bool:
    return _proper_unlike(p) and Fraction(wrong_numerator, wrong_denominator) != p.fraction_sum()


def _across_applies(p: Problem) -> bool:
    return _proper_unlike(p) and _differs(p, p.a + p.c, p.b + p.d)


def _across(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = (
        f"adds the tops: {p.a}+{p.c}={p.a + p.c}",
        f"adds the bottoms too: {p.b}+{p.d}={p.b + p.d}",
    )
    return f"{p.a + p.c}/{p.b + p.d}", steps


def _larger_bottom_applies(p: Problem) -> bool:
    return _proper_unlike(p) and _differs(p, p.a + p.c, max(p.b, p.d))


def _larger_bottom(p: Problem) -> tuple[str, tuple[str, ...]]:
    bottom = max(p.b, p.d)
    steps = (
        f"adds the tops: {p.a}+{p.c}={p.a + p.c}",
        f"keeps the bigger bottom {bottom} without making the bottoms the same",
    )
    return f"{p.a + p.c}/{bottom}", steps


ADD_ACROSS = Malrule(
    "FRAC.ADD_ACROSS", (TOPIC,), (5,), SOURCE,
    "Adds the tops and the bottoms separately, so 1/2 plus 1/3 becomes 2/5.",
    _across_applies, _across,
)  # fmt: skip
ADD_TOP_KEEP_LARGER_BOTTOM = Malrule(
    "FRAC.ADD_TOP_KEEP_LARGER_BOTTOM", (TOPIC,), (5,), SOURCE,
    "Adds the tops and keeps the bigger bottom, so 1/2 plus 1/3 becomes 2/3.",
    _larger_bottom_applies, _larger_bottom,
)  # fmt: skip

RULES = (ADD_ACROSS, ADD_TOP_KEEP_LARGER_BOTTOM)
