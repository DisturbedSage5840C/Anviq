"""A concrete problem a child is asked (numeracy or literacy), and the plain correct answer."""

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction


class Kind(StrEnum):
    SUBTRACT = "subtract"  # a - b
    ADD = "add"  # a + b
    WRITE_NUMBER = "write_number"  # write the number a in digits, after hearing it said
    COMPARE = "compare"  # which is bigger, a or b
    WORD_MORE_THAN = "word_more_than"  # "a marbles; that is b more than Ravi. How many has Ravi?"
    MULTIPLY = "multiply"  # a x b
    DIVIDE = "divide"  # a / b, with no remainder
    AREA = "area"  # area of a rectangle with length a and breadth b
    ADD_FRACTIONS = "add_fractions"  # a/b + c/d
    WRITE_LARGE_NUMBER = "write_large_number"  # write the number a (up to 6 digits) in digits
    READ_WORD = "read_word"  # read the word `text` aloud
    SPELL_WORD = "spell_word"  # write the word `text`, after hearing it said


@dataclass(frozen=True)
class Problem:
    kind: Kind
    a: int = 0
    b: int = 0
    c: int = 0  # the numerator of the second fraction; used only by ADD_FRACTIONS
    d: int = 0  # the denominator of the second fraction; used only by ADD_FRACTIONS
    text: str = ""  # the word to read or spell; used only by READ_WORD and SPELL_WORD

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
            case Kind.MULTIPLY | Kind.AREA:
                return str(self.a * self.b)
            case Kind.DIVIDE:
                return str(self._quotient())
            case Kind.ADD_FRACTIONS:
                return _fraction_text(self.fraction_sum())
            case Kind.WRITE_LARGE_NUMBER:
                return str(self.a)
            case Kind.READ_WORD | Kind.SPELL_WORD:
                return self.text
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
            case Kind.MULTIPLY:
                return f"{self.a} \u00d7 {self.b}"
            case Kind.DIVIDE:
                return f"{self.a} \u00f7 {self.b}"
            case Kind.AREA:
                return f"area of a rectangle of length {self.a} and breadth {self.b}"
            case Kind.ADD_FRACTIONS:
                return f"{self.a}/{self.b} + {self.c}/{self.d}"
            case Kind.WRITE_LARGE_NUMBER:
                return f"write {self.a} in digits"
            case Kind.READ_WORD:
                return f"read the word '{self.text}' aloud"
            case Kind.SPELL_WORD:
                return f"write the word '{self.text}' after hearing it"
        raise AssertionError(self.kind)  # pragma: no cover

    def fraction_sum(self) -> Fraction:
        """a/b + c/d as one reduced fraction."""
        if self.b == 0 or self.d == 0:
            raise ValueError(f"a fraction needs a non-zero denominator: {self.statement()}")
        return Fraction(self.a, self.b) + Fraction(self.c, self.d)

    def _quotient(self) -> int:
        if self.b == 0 or self.a % self.b:
            raise ValueError(f"cannot divide {self.a} by {self.b} exactly")
        return self.a // self.b


def _fraction_text(value: Fraction) -> str:
    """'5/6', or a plain whole number when the denominator is 1."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def digits(n: int) -> tuple[int, int]:
    """(tens, ones) of a number below 100."""
    return divmod(n, 10)
