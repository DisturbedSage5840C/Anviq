"""Shared column-arithmetic helpers, so each malrule reads as the one mistake it makes."""

from math import lcm

from app.core.children.problem import Kind, Problem, digits


def needs_borrow(a: int, b: int) -> bool:
    return digits(a)[1] < digits(b)[1]


def correct_subtraction_steps(a: int, b: int) -> tuple[str, ...]:
    (ta, oa), (tb, ob) = digits(a), digits(b)
    if oa >= ob:
        return (f"ones: {oa}-{ob}={oa - ob}", f"tens: {ta}-{tb}={ta - tb}")
    return (
        f"ones: {oa} is smaller than {ob}, borrow 1 ten, {10 + oa}-{ob}={10 + oa - ob}",
        f"tens: {ta}-1-{tb}={ta - 1 - tb}",
    )


def _multiply_steps(a: int, b: int) -> tuple[str, ...]:
    if b < 10:
        (ta, oa), carry = digits(a), (digits(a)[1] * b) // 10
        return (
            f"ones: {oa} times {b} is {oa * b}"
            + (f", write {oa * b % 10} and carry {carry}" if carry else ""),
            f"tens: {ta} times {b} is {ta * b}"
            + (f", plus {carry} is {ta * b + carry}" if carry else ""),
        )
    tens_b, ones_b = digits(b)
    return (
        f"multiply by the ones digit: {a} times {ones_b} is {a * ones_b}",
        f"put a zero in the ones place, then multiply by the tens digit: "
        f"{a} times {tens_b} is {a * tens_b}, "
        f"written as {a * tens_b * 10}",
        f"add: {a * ones_b} + {a * tens_b * 10} = {a * b}",
    )


def _fraction_steps(p: Problem) -> tuple[str, ...]:
    common = lcm(p.b, p.d)
    top_a, top_c = p.a * (common // p.b), p.c * (common // p.d)
    return (
        f"make the bottoms the same: {p.b} and {p.d} both go into {common}",
        f"{p.a}/{p.b} = {top_a}/{common} and {p.c}/{p.d} = {top_c}/{common}",
        f"add only the tops: {top_a}+{top_c}={top_a + top_c}, "
        f"so the answer is {p.correct_answer()}",
    )


def _large_number_steps(a: int) -> tuple[str, ...]:
    thousands, rest = divmod(a, 1000)
    return (
        f"write the thousands part: {thousands}",
        f"the last three places must be filled, so write {rest} as {rest:03d}",
        f"put them together: {a}",
    )


def correct_steps(problem: Problem) -> tuple[str, ...]:
    """The right method in words, for a child who solves it properly and can now explain it."""
    if problem.kind is Kind.SUBTRACT and problem.a >= 10 and problem.b >= 10:
        return correct_subtraction_steps(problem.a, problem.b)
    if problem.kind is Kind.ADD and problem.a >= 10 and problem.b >= 10:
        (ta, oa), (tb, ob) = digits(problem.a), digits(problem.b)
        ones = oa + ob
        carry = ones // 10
        return (
            f"ones: {oa}+{ob}={ones}" + (", carry 1 ten" if carry else ""),
            f"tens: {ta}+{tb}" + ("+1" if carry else "") + f"={ta + tb + carry}",
        )
    if problem.kind is Kind.MULTIPLY and problem.a >= 10 and problem.b >= 2:
        return _multiply_steps(problem.a, problem.b)
    if problem.kind is Kind.DIVIDE:
        quotient = problem.correct_answer()
        return (
            f"{problem.b} times {quotient} is {problem.a}, so {problem.statement()} is {quotient}",
        )
    if problem.kind is Kind.AREA:
        return (
            f"area is length times breadth: "
            f"{problem.a} times {problem.b} is {problem.a * problem.b}",
        )
    if problem.kind is Kind.ADD_FRACTIONS:
        return _fraction_steps(problem)
    if problem.kind is Kind.WRITE_LARGE_NUMBER:
        return _large_number_steps(problem.a)
    if problem.kind is Kind.READ_WORD:
        return (f"looks at every letter of {problem.text} and sounds it out in order",)
    if problem.kind is Kind.SPELL_WORD:
        return (f"says {problem.text} slowly and writes down each sound, then checks the spelling",)
    return (f"worked out {problem.statement()} carefully, one step at a time",)
