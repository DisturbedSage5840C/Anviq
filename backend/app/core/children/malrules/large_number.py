"""Class 4 place-value misconception: writing numbers in the thousands from the words."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem

TOPIC = "NUM.G4.PV.LARGE_NUMBER"
SOURCE = "Place-value literature (number-word to digit transcoding errors, larger numbers)"
THOUSAND = 1000
HUNDRED = 100


def _zeros_lost_case(p: Problem) -> bool:
    return (
        p.kind is Kind.WRITE_LARGE_NUMBER
        and THOUSAND <= p.a <= 999_999
        and 0 < p.a % THOUSAND < HUNDRED
    )


def _joins_the_parts(p: Problem) -> tuple[str, tuple[str, ...]]:
    thousands, rest = divmod(p.a, THOUSAND)
    steps = (
        f"hears the thousands part and writes {thousands}",
        f"hears the last part as {rest} and writes it straight after, "
        "with no zeros to fill the gap",
    )
    return f"{thousands}{rest}", steps


ZEROS_DROPPED = Malrule(
    "PVL.ZEROS_DROPPED", (TOPIC,), (4, 5), SOURCE,
    "Joins the thousands and the rest without the zeros, like forty-five thousand six as 456.",
    _zeros_lost_case, _joins_the_parts,
)  # fmt: skip

RULES = (ZEROS_DROPPED,)
