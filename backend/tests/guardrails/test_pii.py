import pytest

from app.guardrails.pii import scrub


@pytest.mark.parametrize(
    "text",
    [
        "call me on 9876543210",
        "call me on +91 98765 43210",
        "call me on 98765-43210",
        "call me on 919876543210",
    ],
)
def test_indian_phone_numbers_are_redacted(text: str):
    result = scrub(text)

    assert "[phone]" in result
    assert "98765" not in result


def test_aadhaar_like_numbers_are_redacted():
    assert scrub("my id is 2345 6789 0123") == "my id is [id]"


def test_emails_are_redacted():
    assert scrub("mail teacher.k@example.org please") == "mail [email] please"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("In my class, Pinky cannot subtract", "In my class, [बच्चा] cannot subtract"),
        ("मेरी क्लास में पिंकी घटाना नहीं जानती", "मेरी क्लास में [बच्चा] घटाना नहीं जानती"),
        ("rahul and SONU were stuck", "[बच्चा] and [बच्चा] were stuck"),
    ],
)
def test_child_names_become_a_placeholder(text: str, expected: str):
    assert scrub(text) == expected


@pytest.mark.parametrize("name", ["Riya", "Aman", "Meena", "रिया", "अमन", "मीना"])
def test_the_ai_children_are_never_scrubbed(name: str):
    text = f"{name}, how did you get that?"

    assert scrub(text) == text


def test_names_inside_longer_words_are_left_alone():
    assert scrub("Ravine and Sonuka are places") == "Ravine and Sonuka are places"


def test_text_without_personal_data_is_unchanged():
    text = "52 में से 17 घटाओ, कैसे किया?"

    assert scrub(text) == text


def test_scrubbing_twice_changes_nothing_more():
    once = scrub("Pinky at 9876543210 or a@b.co")

    assert scrub(once) == once


def test_a_phone_number_written_in_devanagari_digits_is_scrubbed():
    assert scrub("मेरा नंबर ९८७६५४३२१० है") == "मेरा नंबर [phone] है"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call ９８７６５４３２１０ now", "call [phone] now"),
        ("mail teacher.k＠example.org please", "mail [email] please"),
        ("ｒａｈｕｌ was stuck", "[बच्चा] was stuck"),
        ("ＰＩＮＫＹ was stuck", "[बच्चा] was stuck"),
    ],
)
def test_compatibility_forms_cannot_hide_personal_data(text: str, expected: str):
    assert scrub(text) == expected
