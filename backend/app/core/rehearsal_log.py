"""What a practice leaves behind: the teacher's scored questions, for the Day-1/Day-14 mirror.

The flow decides *what* happened in a turn and hands it back as a `LoggedTurn`; the router writes it
through the teacher's session, inside the same locked block that decides whether the turn stands.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


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
