"""An executable misconception: a wrong method that Python runs, so no model invents the error.

Plan section 4.6. A child's wrong answer is computed here; the model only puts it into words.
That is what lets the engine hold the misconception on at least 95% of turns.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.core.children.problem import Problem


@dataclass(frozen=True)
class MalruleResult:
    answer: str  # what the child says, e.g. "45"
    steps: tuple[str, ...]  # the child's reasoning, in plain English, one step each
    correct_answer: str
    misconception_id: str


@dataclass(frozen=True)
class Malrule:
    id: str
    topic_ids: tuple[str, ...]
    grades: tuple[int, ...]
    source: str
    summary: str  # one line a teacher can read: what the child is doing wrong
    applies: Callable[[Problem], bool]
    _run: Callable[[Problem], tuple[str, tuple[str, ...]]]

    def run(self, problem: Problem) -> MalruleResult:
        if not self.applies(problem):
            raise ValueError(f"{self.id} does not apply to {problem.statement()}")
        answer, steps = self._run(problem)
        return MalruleResult(answer, steps, problem.correct_answer(), self.id)
