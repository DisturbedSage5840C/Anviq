"""Class 4 mensuration misconceptions: asked for area, the child gives something else."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem

TOPIC = "NUM.G4.AREA.PERIMETER"
SOURCE = "Area and perimeter confusion literature (additive versus multiplicative measures)"


def _asks_area(p: Problem) -> bool:
    return p.kind is Kind.AREA and p.a >= 1 and p.b >= 1


def _adds_applies(p: Problem) -> bool:
    return _asks_area(p) and p.a + p.b != p.a * p.b


def _adds(p: Problem) -> tuple[str, tuple[str, ...]]:
    return str(p.a + p.b), (f"adds the length and the breadth: {p.a}+{p.b}={p.a + p.b}",)


def _perimeter_applies(p: Problem) -> bool:
    return _asks_area(p) and 2 * (p.a + p.b) != p.a * p.b


def _perimeter(p: Problem) -> tuple[str, tuple[str, ...]]:
    total = 2 * (p.a + p.b)
    steps = (
        f"walks round the edge: {p.a}+{p.b}+{p.a}+{p.b}",
        f"gets {total} and calls it the area",
    )
    return str(total), steps


ADDS_SIDES = Malrule(
    "AREA.ADDS_SIDES", (TOPIC,), (4, 5), SOURCE,
    "Adds the length and breadth instead of multiplying them to find the area.",
    _adds_applies, _adds,
)  # fmt: skip
GIVES_PERIMETER = Malrule(
    "AREA.GIVES_PERIMETER", (TOPIC,), (4, 5), SOURCE,
    "Gives the distance round the edge (the perimeter) when asked for the area.",
    _perimeter_applies, _perimeter,
)  # fmt: skip

RULES = (ADDS_SIDES, GIVES_PERIMETER)
