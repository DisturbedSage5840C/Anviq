"""Comparing two-digit numbers."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem, digits

TOPIC = "NUM.G1.CMP.TWO_DIGIT"


def _fooled(p: Problem) -> bool:
    if p.kind is not Kind.COMPARE or not (10 <= p.a <= 99 and 10 <= p.b <= 99) or p.a == p.b:
        return False
    oa, ob = digits(p.a)[1], digits(p.b)[1]
    return oa != ob and (p.a > p.b) != (oa > ob)


def _ones_decide(p: Problem) -> tuple[str, tuple[str, ...]]:
    oa, ob = digits(p.a)[1], digits(p.b)[1]
    pick = p.a if oa > ob else p.b
    steps = (
        f"looks at the last digits only: {oa} and {ob}",
        f"{max(oa, ob)} is bigger than {min(oa, ob)}, so {pick} must be the bigger number",
    )
    return str(pick), steps


ONES_DIGIT_DECIDES = Malrule(
    "CMP.ONES_DIGIT_DECIDES", (TOPIC,), (1, 2), "Comparison-misconception research",
    "Decides which number is bigger by the ones digit alone.",
    _fooled, _ones_decide,
)  # fmt: skip

RULES = (ONES_DIGIT_DECIDES,)
