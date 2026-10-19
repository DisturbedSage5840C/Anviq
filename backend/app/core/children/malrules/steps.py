"""Shared column-arithmetic helpers, so each malrule reads as the one mistake it makes."""

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
    return (f"worked out {problem.statement()} carefully, one step at a time",)
