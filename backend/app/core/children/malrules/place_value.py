"""Place-value misconceptions: writing two-digit numbers."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem, digits

TOPIC = "NUM.G1.PV.TWO_DIGIT"
SOURCE = "Place-value literature (number-word to digit transcoding errors)"


def _writable(p: Problem) -> bool:
    return p.kind is Kind.WRITE_NUMBER and 11 <= p.a <= 99 and digits(p.a)[1] > 0


def _concat(p: Problem) -> tuple[str, tuple[str, ...]]:
    tens, ones = digits(p.a)
    steps = (
        f"hears the number as {tens * 10} and {ones}",
        f"writes {tens * 10} then {ones} side by side",
    )
    return f"{tens * 10}{ones}", steps


def _reversal_case(p: Problem) -> bool:
    if not _writable(p):
        return False
    tens, ones = digits(p.a)
    return tens != ones


def _reversed(p: Problem) -> tuple[str, tuple[str, ...]]:
    tens, ones = digits(p.a)
    steps = (f"hears the ones first and writes {ones}", f"then writes the tens {tens}")
    return f"{ones}{tens}", steps


CONCAT_WRITE = Malrule(
    "PV.CONCAT_WRITE", (TOPIC,), (1, 2), SOURCE,
    "Writes a two-digit number as its parts joined up, like fifty-two as 502.",
    _writable, _concat,
)  # fmt: skip
DIGIT_REVERSAL = Malrule(
    "PV.DIGIT_REVERSAL", (TOPIC,), (1, 2), SOURCE,
    "Swaps the tens and ones digits when writing a number.",
    _reversal_case, _reversed,
)  # fmt: skip

RULES = (CONCAT_WRITE, DIGIT_REVERSAL)
