import pytest

from app.speech.voices import PERSONAS, voice_for


@pytest.mark.parametrize("provider", ["sarvam", "google"])
def test_every_persona_has_a_voice_for_each_provider(provider: str) -> None:
    for persona in PERSONAS:
        assert voice_for(provider, persona).speaker


def test_meena_speaks_slower_than_riya() -> None:
    assert voice_for("sarvam", "meena").pace < voice_for("sarvam", "riya").pace


def test_unknown_persona_is_rejected() -> None:
    with pytest.raises(KeyError):
        voice_for("sarvam", "nobody")
