"""What a practice leaves behind: the teacher's scored questions, for the Day-1/Day-14 mirror.

The flow decides *what* happened in a turn; the log decides where it is kept. Keeping the two apart
means the practice never depends on a database being up: a log that fails is only a lost row.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol


@dataclass(frozen=True)
class LoggedTurn:
    """One teacher question as the coach scored it. `teacher_text` is already scrubbed."""

    move_id: int
    topic_id: str
    week: str
    teacher_text: str
    criteria: Mapping[str, bool]
    child_name: str | None = None
    malrule_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", MappingProxyType(dict(self.criteria)))


class RehearsalLog(Protocol):
    async def begin(self, teacher: bytes) -> None:
        """A practice is starting: close whatever the teacher left open before."""
        ...

    async def record(self, teacher: bytes, turn: LoggedTurn) -> None: ...

    async def end(self, teacher: bytes) -> None:
        """The practice is over; the next scored turn starts a new session."""
        ...


class NoRehearsalLog:
    """Keeps nothing, for a flow that is not wired to a database."""

    async def begin(self, teacher: bytes) -> None:
        return None

    async def record(self, teacher: bytes, turn: LoggedTurn) -> None:
        return None

    async def end(self, teacher: bytes) -> None:
        return None
