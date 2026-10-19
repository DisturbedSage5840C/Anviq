"""Word-problem keyword traps."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem

TOPIC = "NUM.G3.WP.COMPARE"


def _more_than(p: Problem) -> bool:
    return p.kind is Kind.WORD_MORE_THAN and 1 <= p.b < p.a <= 99


def _adds(p: Problem) -> tuple[str, tuple[str, ...]]:
    steps = ("sees the word 'more' and decides it is a plus sum", f"{p.a}+{p.b}={p.a + p.b}")
    return str(p.a + p.b), steps


KEYWORD_MORE_MEANS_ADD = Malrule(
    "WP.KEYWORD_MORE_MEANS_ADD", (TOPIC,), (2, 3), "Word-problem keyword-strategy research",
    "Sees the word 'more' and adds, without asking who has more.",
    _more_than, _adds,
)  # fmt: skip

RULES = (KEYWORD_MORE_MEANS_ADD,)
