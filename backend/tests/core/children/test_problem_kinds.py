import pytest

from app.core.children.problem import Kind, Problem


@pytest.mark.parametrize(
    ("problem", "answer"),
    [
        (Problem(Kind.MULTIPLY, 47, 6), "282"),
        (Problem(Kind.MULTIPLY, 34, 26), "884"),
        (Problem(Kind.DIVIDE, 612, 6), "102"),
        (Problem(Kind.AREA, 12, 5), "60"),
        (Problem(Kind.ADD_FRACTIONS, 1, 2, 1, 3), "5/6"),
        (Problem(Kind.ADD_FRACTIONS, 1, 4, 1, 4), "1/2"),
        (Problem(Kind.ADD_FRACTIONS, 1, 2, 1, 2), "1"),
        (Problem(Kind.WRITE_LARGE_NUMBER, 45006), "45006"),
    ],
)
def test_correct_answer_for_class_four_and_five_kinds(problem: Problem, answer: str) -> None:
    assert problem.correct_answer() == answer


@pytest.mark.parametrize(
    ("problem", "fragment"),
    [
        (Problem(Kind.MULTIPLY, 47, 6), "47 × 6"),
        (Problem(Kind.DIVIDE, 612, 6), "612 ÷ 6"),
        (Problem(Kind.AREA, 12, 5), "length 12"),
        (Problem(Kind.ADD_FRACTIONS, 1, 2, 1, 3), "1/2 + 1/3"),
        (Problem(Kind.WRITE_LARGE_NUMBER, 45006), "45006"),
    ],
)
def test_statement_names_the_numbers_in_the_problem(problem: Problem, fragment: str) -> None:
    assert fragment in problem.statement()


def test_a_problem_is_frozen_and_c_and_d_default_to_zero() -> None:
    problem = Problem(Kind.ADD, 4, 5)

    assert (problem.c, problem.d) == (0, 0)
    with pytest.raises(AttributeError):
        problem.a = 9  # type: ignore[misc]


def test_a_fraction_with_a_zero_denominator_is_an_error() -> None:
    with pytest.raises(ValueError, match="denominator"):
        Problem(Kind.ADD_FRACTIONS, 1, 0, 1, 2).correct_answer()


def test_dividing_by_zero_or_with_a_remainder_is_an_error() -> None:
    with pytest.raises(ValueError, match="divide"):
        Problem(Kind.DIVIDE, 7, 0).correct_answer()
    with pytest.raises(ValueError, match="divide"):
        Problem(Kind.DIVIDE, 7, 2).correct_answer()
