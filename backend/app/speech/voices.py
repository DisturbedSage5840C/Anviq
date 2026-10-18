"""Persona voices per provider. Speakers are config-level choices, reviewed by ear."""

from app.speech.base import Voice

PERSONAS = ("riya", "aman", "meena", "coach")
COACH_PERSONA = "coach"

# Bulbul v3 speakers. Meena is the shy child, so she speaks slower.
_SARVAM = {
    "riya": Voice("priya", 1.1),
    "aman": Voice("aditya", 1.0),
    "meena": Voice("neha", 0.85),
    "coach": Voice("ritu", 1.0),
}
# Google only needs a gender; the language picks the concrete voice.
_GOOGLE = {
    "riya": Voice("female", 1.1),
    "aman": Voice("male", 1.0),
    "meena": Voice("female", 0.85),
    "coach": Voice("female", 1.0),
}
_BY_PROVIDER = {"sarvam": _SARVAM, "google": _GOOGLE}


def voice_for(provider: str, persona: str) -> Voice:
    return _BY_PROVIDER[provider][persona]
