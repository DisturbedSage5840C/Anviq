"""Class 4 multiplication misconceptions: multi-digit work in columns."""

from app.core.children.malrules.base import Malrule
from app.core.children.problem import Kind, Problem, digits

TOPIC = "NUM.G4.MUL.MULTI_DIGIT"
SOURCE = "Multi-digit multiplication error literature (carrying and partial products)"


def _one_digit_with_carry(p: Problem) -> bool:
    return (
        p.kind is Kind.MULTIPLY and 10 <= p.a <= 99 and 2 <= p.b <= 9 and digits(p.a)[1] * p.b >= 10
    )


def _drops_the_carry(p: Problem) -> tuple[str, tuple[str, ...]]:
    tens, ones = digits(p.a)
    kept = (ones * p.b) % 10
    steps = (
        f"ones: {ones} times {p.b} is {ones * p.b}, writes {kept} and forgets to carry",
        f"tens: {tens} times {p.b} is {tens * p.b}, writes it as it is",
    )
    return str(tens * p.b * 10 + kept), steps


def _two_digit_with_ones(p: Problem) -> bool:
    return p.kind is Kind.MULTIPLY and 10 <= p.a <= 99 and 10 <= p.b <= 99 and p.b % 10 != 0


def _no_placeholder_zero(p: Problem) -> tuple[str, tuple[str, ...]]:
    tens_b, ones_b = digits(p.b)
    first, second = p.a * ones_b, p.a * tens_b
    steps = (
        f"multiplies by the ones digit: {p.a} times {ones_b} is {first}",
        f"multiplies by the tens digit {tens_b} but leaves out the placeholder zero: {second}",
        f"adds {first} and {second}",
    )
    return str(first + second), steps


FORGET_CARRY = Malrule(
    "MUL.FORGET_CARRY", (TOPIC,), (4, 5), SOURCE,
    "Forgets to carry the tens from the ones product, like 47 times 6 as 242.",
    _one_digit_with_carry, _drops_the_carry,
)  # fmt: skip
NO_PLACEHOLDER_ZERO = Malrule(
    "MUL.NO_PLACEHOLDER_ZERO", (TOPIC,), (4, 5), SOURCE,
    "Skips the zero placeholder on the second line of a two-digit multiplication.",
    _two_digit_with_ones, _no_placeholder_zero,
)  # fmt: skip

RULES = (FORGET_CARRY, NO_PLACEHOLDER_ZERO)
