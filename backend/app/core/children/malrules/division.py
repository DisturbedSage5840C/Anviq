"""Class 4 division misconception: a zero in the middle of the quotient."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem

TOPIC = "NUM.G4.DIV.ZERO_IN_QUOTIENT"
SOURCE = "Long-division error literature (placeholder zero in the quotient)"


def _quotient_with_inner_zero(p: Problem) -> bool:
    if p.kind is not Kind.DIVIDE or not 2 <= p.b <= 9 or p.a % p.b:
        return False
    hundreds, rest = divmod(p.a // p.b, 100)
    tens, units = divmod(rest, 10)
    return 1 <= hundreds <= 9 and tens == 0 and units != 0


def _drops_the_zero(p: Problem) -> tuple[str, tuple[str, ...]]:
    quotient = p.a // p.b
    hundreds, units = quotient // 100, quotient % 10
    steps = (
        f"divides the hundreds and gets {hundreds}",
        "brings down the next digit, sees it is too small, and writes nothing for the tens",
        f"the ones give {units}, so writes {hundreds}{units}",
    )
    return f"{hundreds}{units}", steps


DROPS_ZERO_IN_QUOTIENT = Malrule(
    "DIV.DROPS_ZERO_IN_QUOTIENT", (TOPIC,), (4, 5), SOURCE,
    "Leaves out the zero in the middle of the quotient, like 612 divided by 6 as 12.",
    _quotient_with_inner_zero, _drops_the_zero,
)  # fmt: skip

RULES = (DROPS_ZERO_IN_QUOTIENT,)
