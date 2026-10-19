"""The three AI children (plan section 3.3 B). Their names are allow-listed by the PII scrubber."""

import re
from dataclasses import dataclass
from enum import StrEnum


class ChildState(StrEnum):
    """How far a child has come, driven by how well the teacher asks (plan section 3.3 B)."""

    CONFUSED = "confused"
    EXPLAINING = "explaining"
    SELF_CORRECTING = "self-correcting"

    def next(self) -> "ChildState":
        order = list(ChildState)
        return order[min(order.index(self) + 1, len(order) - 1)]


@dataclass(frozen=True)
class Persona:
    key: str  # also the voice key in speech/voices.py
    name: str
    name_hi: str
    age: int
    temperament: str


RIYA = Persona("riya", "Riya", "रिया", 7, "Confident and quick, often wrong, sure of herself.")
AMAN = Persona(
    "aman", "Aman", "अमन", 8,
    "Gets the right answer but cannot say how. Until the teacher helps him, says he does not "
    "know, it just came to him.",
)  # fmt: skip
MEENA = Persona(
    "meena", "Meena", "मीना", 6, "Shy and slow to speak. Hesitates, says umm, speaks very softly."
)

PERSONAS = (RIYA, AMAN, MEENA)
_BY_KEY = {persona.key: persona for persona in PERSONAS}
_ADDRESSED = re.compile(r"(?<![\wऀ-ॿ])(riya|aman|meena|रिया|अमन|मीना)(?![\wऀ-ॿ])", re.IGNORECASE)
_NAME_TO_KEY = {
    "riya": "riya",
    "aman": "aman",
    "meena": "meena",
    "रिया": "riya",
    "अमन": "aman",
    "मीना": "meena",
}


def persona_for(key: str) -> Persona:
    return _BY_KEY[key]


def addressed_child(text: str) -> Persona | None:
    """The child the teacher named first in this turn, in either script, else None."""
    match = _ADDRESSED.search(text)
    return persona_for(_NAME_TO_KEY[match.group(1).casefold()]) if match else None
