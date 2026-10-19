"""Two-digit subtraction misconceptions (Brown & Burton BUGGY; VanLehn)."""

from app.core.children.malrules.base import Malrule
from app.core.children.malrules.steps import correct_subtraction_steps, needs_borrow
from app.core.children.problem import Kind, Problem, digits

TOPIC_REGROUP = "NUM.G2.SUB.REGROUP"
TOPIC_ZERO = "NUM.G2.SUB.ZERO"
GRADES = (2, 3)
SOURCE = "Brown & Burton (1978) BUGGY; VanLehn (1990)"


def _two_digit_sub(p: Problem) -> bool:
    return p.kind is Kind.SUBTRACT and 10 <= p.b < p.a <= 99


def _borrow_case(p: Problem) -> bool:
    return _two_digit_sub(p) and needs_borrow(p.a, p.b)


def _smaller_from_larger(p: Problem) -> tuple[str, tuple[str, ...]]:
    (ta, oa), (tb, ob) = digits(p.a), digits(p.b)
    tens, ones = abs(ta - tb), abs(oa - ob)
    big, small = max(oa, ob), min(oa, ob)
    steps = (
        f"ones: {oa} and {ob}, take the smaller from the larger: {big}-{small}={ones}",
        f"tens: {ta} and {tb}: {max(ta, tb)}-{min(ta, tb)}={tens}",
    )
    return str(10 * tens + ones), steps


def _borrow_no_decrement(p: Problem) -> tuple[str, tuple[str, ...]]:
    (ta, oa), (tb, ob) = digits(p.a), digits(p.b)
    ones, tens = 10 + oa - ob, ta - tb
    steps = (
        f"ones: {oa} is smaller than {ob}, so borrow 1 ten: {10 + oa}-{ob}={ones}",
        f"tens: forgot to cross out the borrowed ten, so {ta}-{tb}={tens}",
    )
    return str(10 * tens + ones), steps


def _zero_minus_n(p: Problem) -> tuple[str, tuple[str, ...]]:
    (ta, _), (tb, ob) = digits(p.a), digits(p.b)
    tens = ta - tb
    steps = (f"ones: 0 minus {ob}: can't, so just write the {ob}", f"tens: {ta}-{tb}={tens}")
    return str(10 * tens + ob), steps


def _n_minus_zero(p: Problem) -> tuple[str, tuple[str, ...]]:
    (ta, oa), (tb, _) = digits(p.a), digits(p.b)
    tens = ta - tb
    steps = (f"ones: {oa} minus 0: when 0 is involved the answer is 0", f"tens: {ta}-{tb}={tens}")
    return str(10 * tens), steps


def _written_backwards(p: Problem) -> tuple[str, tuple[str, ...]]:
    tens, ones = digits(p.a - p.b)
    steps = (
        *correct_subtraction_steps(p.a, p.b),
        f"writing: put the ones answer {ones} first and the tens answer {tens} after it",
    )
    return f"{ones}{tens}", steps


def _backwards_case(p: Problem) -> bool:
    if not _two_digit_sub(p):
        return False
    tens, ones = digits(p.a - p.b)
    return tens > 0 and ones > 0 and tens != ones


SMALLER_FROM_LARGER = Malrule(
    "SUB.SMALLER_FROM_LARGER", (TOPIC_REGROUP,), GRADES, SOURCE,
    "In each column takes the smaller digit from the larger, whichever is on top.",
    _borrow_case, _smaller_from_larger,
)  # fmt: skip
BORROW_NO_DECREMENT = Malrule(
    "SUB.BORROW_NO_DECREMENT", (TOPIC_REGROUP,), GRADES, SOURCE,
    "Borrows a ten for the ones but forgets to reduce the tens digit.",
    _borrow_case, _borrow_no_decrement,
)  # fmt: skip
ZERO_MINUS_N_IS_N = Malrule(
    "SUB.ZERO_MINUS_N_IS_N", (TOPIC_ZERO,), GRADES, SOURCE,
    "When the top digit is 0, writes the bottom digit instead of borrowing.",
    lambda p: _two_digit_sub(p) and digits(p.a)[1] == 0 and digits(p.b)[1] > 0,
    _zero_minus_n,
)  # fmt: skip
N_MINUS_ZERO_IS_ZERO = Malrule(
    "SUB.N_MINUS_ZERO_IS_ZERO", (TOPIC_ZERO,), GRADES, SOURCE,
    "Thinks a number minus zero is zero.",
    lambda p: _two_digit_sub(p) and digits(p.b)[1] == 0 and digits(p.a)[1] > 0 and p.a - p.b >= 10,
    _n_minus_zero,
)  # fmt: skip
ALWAYS_LEFT_TO_RIGHT = Malrule(
    "SUB.ALWAYS_LEFT_TO_RIGHT", (TOPIC_REGROUP,), GRADES, SOURCE,
    "Works the columns right to left but writes the answers down in working order.",
    _backwards_case, _written_backwards,
)  # fmt: skip

RULES = (
    SMALLER_FROM_LARGER,
    BORROW_NO_DECREMENT,
    ZERO_MINUS_N_IS_N,
    N_MINUS_ZERO_IS_ZERO,
    ALWAYS_LEFT_TO_RIGHT,
)
