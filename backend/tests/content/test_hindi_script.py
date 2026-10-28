import pytest

from app.content.copy import render
from app.core.intents import parse_language

LATIN_NAMES = ("Anviq", "Hindi", "English")
LANGUAGE_PROMPT_KEYS = ("welcome", "ask_language", "language_retry", "consent_withdrawn", "deleted")


@pytest.mark.parametrize("key", LANGUAGE_PROMPT_KEYS)
def test_hindi_copy_writes_the_product_and_language_names_in_devanagari(key: str):
    text = render(key, "hi")

    assert not any(name in text for name in LATIN_NAMES)


def test_the_hindi_language_question_still_names_the_words_a_teacher_may_reply_with():
    prompt = render("ask_language", "hi")

    assert parse_language("हिंदी") == "hi"
    assert parse_language("अंग्रेज़ी") == "en"
    assert "हिंदी" in prompt and "अंग्रेज़ी" in prompt
