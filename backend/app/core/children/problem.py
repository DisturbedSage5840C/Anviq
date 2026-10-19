"""A concrete numeracy problem a child is asked, and the plain correct answer to it."""

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    SUBTRACT = "subtract"  # a - b
    ADD = "add"  # a + b
    WRITE_NUMBER = "write_number"  # write the number a in digits, after hearing it said
    COMPARE = "compare"  # which is bigger, a or b
    WORD_MORE_THAN = "word_more_than"  # "a marbles; that is b more than Ravi. How many has Ravi?"


@dataclass(frozen=True)
class Problem:
    kind: Kind
    a: int
    b: int = 0

    def correct_answer(self) -> str:
        match self.kind:
            case Kind.SUBTRACT | Kind.WORD_MORE_THAN:
                return str(self.a - self.b)
            case Kind.ADD:
                return str(self.a + self.b)
            case Kind.WRITE_NUMBER:
                return str(self.a)
            case Kind.COMPARE:
                return str(max(self.a, self.b))
        raise AssertionError(self.kind)  # pragma: no cover

    def statement(self) -> str:
        """The problem in digits, for the model and for people reading a trace."""
        match self.kind:
            case Kind.SUBTRACT:
                return f"{self.a} - {self.b}"
            case Kind.ADD:
                return f"{self.a} + {self.b}"
            case Kind.WRITE_NUMBER:
                return f"write {self.a} in digits"
            case Kind.COMPARE:
                return f"which is bigger, {self.a} or {self.b}"
            case Kind.WORD_MORE_THAN:
                return f"has {self.a}, {self.b} more than another child; how many has the other"
        raise AssertionError(self.kind)  # pragma: no cover


def digits(n: int) -> tuple[int, int]:
    """(tens, ones) of a number below 100."""
    return divmod(n, 10)
