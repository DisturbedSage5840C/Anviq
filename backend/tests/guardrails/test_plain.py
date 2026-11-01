import pytest

from app.guardrails.plain import plain_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Well done \U0001f44d", "Well done"),
        ("\U0001f331 Good try", "Good try"),
        ("**Bold** and __also bold__", "Bold and also bold"),
        ("## Heading\nBody", "Heading\nBody"),
        ("Use `tens` blocks", "Use tens blocks"),
        ("Thumbs️ up", "Thumbs up"),
        ("Plain sentence.", "Plain sentence."),
        ("Nice \U0001f44d. Try again \U0001f331!", "Nice. Try again!"),
        ("\u0905\u091a\u094d\u091b\u093e \U0001f44d\u0964", "\u0905\u091a\u094d\u091b\u093e\u0964"),
        ("", ""),
    ],
)
def test_plain_text_drops_emoji_and_markdown(raw: str, expected: str):
    assert plain_text(raw) == expected


def test_plain_text_keeps_line_breaks_and_dash_lists():
    raw = "Steps:\n- Show 12\n- Group in tens"

    assert plain_text(raw) == raw


def test_plain_text_keeps_devanagari_and_arithmetic():
    raw = "12 × 3 = 36, अंकुर"

    assert plain_text(raw) == raw


def test_plain_text_is_idempotent():
    once = plain_text("**Hi** \U0001f331 there")

    assert plain_text(once) == once
