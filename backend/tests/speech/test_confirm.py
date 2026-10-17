import pytest

from app.speech.base import Transcript
from app.speech.confirm import needs_confirmation


def transcript(text: str, confidence: float | None) -> Transcript:
    return Transcript(text=text, language_code="hi-IN", confidence=confidence, duration_s=4.0)


def test_confident_transcript_is_accepted() -> None:
    assert not needs_confirmation(transcript("कल दो अंकों का घटाना पढ़ाना है", 0.93))


def test_low_confidence_asks_for_confirmation() -> None:
    assert needs_confirmation(transcript("कल दो अंकों का घटाना पढ़ाना है", 0.41))


def test_unknown_confidence_is_trusted() -> None:
    # Providers that give no score must not make every turn a confirm-back.
    assert not needs_confirmation(transcript("कल दो अंकों का घटाना पढ़ाना है", None))


@pytest.mark.parametrize("text", ["", "  ", "।।", "a"])
def test_very_short_transcript_asks_for_confirmation_unless_a_known_answer(text: str) -> None:
    assert needs_confirmation(transcript(text, 0.99))


@pytest.mark.parametrize("text", ["हाँ", "नहीं", "yes", "No", "हाँ, मिटाओ"])
def test_short_yes_no_answers_are_not_second_guessed(text: str) -> None:
    assert not needs_confirmation(transcript(text, 0.99))
