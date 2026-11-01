"""to_spoken: what the text-to-speech engine should read, derived from what the teacher sees."""

import pytest

from app.speech.prepare import SPOKEN_MAX_CHARS, to_spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("**Bold** and *soft* words", "Bold and soft words"),
        ("# Heading\nBody", "Heading. Body"),
        ("- one\n- two", "one. two"),
        ("• one\n• two", "one. two"),
        ("Use `place value` here", "Use place value here"),
    ],
)
def test_strips_markdown_markers(written: str, spoken: str) -> None:
    assert to_spoken(written, "en") == spoken


def test_drops_source_lines_in_both_languages() -> None:
    assert to_spoken("Count in tens.\nSource: NISHTHA FLN, p.12", "en") == "Count in tens."
    assert to_spoken("दहाई में गिनो।\nस्रोत: निष्ठा, पृ. 12", "hi") == "दहाई में गिनो।"


def test_drops_urls() -> None:
    spoken = to_spoken("Read more at https://ncert.nic.in/textbook.php today", "en")
    assert "http" not in spoken
    assert "ncert" not in spoken
    assert spoken == "Read more at today"


@pytest.mark.parametrize("symbol", ["👍", "🌱", "🌿", "🌳", "✅", "→", "➜", "⭐"])
def test_drops_emoji_and_arrows(symbol: str) -> None:
    assert to_spoken(f"Good {symbol} work", "en") == "Good work"


@pytest.mark.parametrize(
    ("written", "lang", "spoken"),
    [
        ("3 × 4 = 12", "en", "3 times 4 equals 12"),
        ("12 ÷ 4", "en", "12 divided by 4"),
        ("5 + 2 − 1", "en", "5 plus 2 minus 1"),
        ("3 × 4 = 12", "hi", "3 गुणा 4 बराबर 12"),
        ("50%", "en", "50 percent"),
        ("50%", "hi", "50 प्रतिशत"),
        ("2 cm and 3 kg", "en", "2 centimetres and 3 kilograms"),
        ("2 cm", "hi", "2 सेंटीमीटर"),
        ("1 cm and 1 kg", "en", "1 centimetre and 1 kilogram"),
    ],
)
def test_reads_symbols_and_units_in_words(written: str, lang: str, spoken: str) -> None:
    assert to_spoken(written, lang) == spoken


def test_does_not_expand_units_inside_words() -> None:
    assert to_spoken("The cmd and kgs words stay", "en") == "The cmd and kgs words stay"


def test_collapses_blank_lines_and_spaces() -> None:
    assert to_spoken("One.\n\n\nTwo   three.", "en") == "One. Two three."


def test_cuts_long_text_at_a_sentence_end() -> None:
    sentence = "This is a sentence. "
    spoken = to_spoken(sentence * 200, "en")
    assert len(spoken) <= SPOKEN_MAX_CHARS
    assert spoken.endswith("sentence.")


def test_cuts_long_text_without_sentence_ends_at_a_word() -> None:
    spoken = to_spoken("word " * 1000, "en")
    assert len(spoken) <= SPOKEN_MAX_CHARS
    assert spoken.endswith("word")


def test_respects_a_custom_limit() -> None:
    assert len(to_spoken("Alpha beta. Gamma delta. Epsilon.", "en", max_chars=25)) <= 25


def test_empty_and_markup_only_text_become_empty() -> None:
    assert to_spoken("", "en") == ""
    assert to_spoken("👍 → **", "en") == ""


def test_hindi_danda_counts_as_a_sentence_end() -> None:
    spoken = to_spoken("यह वाक्य है। " * 400, "hi")
    assert len(spoken) <= SPOKEN_MAX_CHARS
    assert spoken.endswith("है।")
