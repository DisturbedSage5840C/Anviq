import pytest

from app.core.intents import (
    GlobalIntent,
    MenuIntent,
    classify_global,
    classify_menu,
    parse_grade,
    parse_language,
    parse_yes_no,
)


@pytest.mark.parametrize(
    "text",
    ["मेरा डेटा मिटाओ", "मेरा डेटा मिटाओ।", "Delete my data", "please delete my data now"],
)
def test_delete_phrases_are_recognised(text: str):
    assert classify_global(text) is GlobalIntent.DELETE


@pytest.mark.parametrize("text", ["बंद करो", "stop", "Stop!", "unsubscribe"])
def test_short_stop_phrases_are_recognised(text: str):
    assert classify_global(text) is GlobalIntent.STOP


def test_stop_inside_a_long_sentence_is_not_an_opt_out():
    assert classify_global("बच्चे बस stop पर खड़े थे जब मैंने पूछा कैसे") is None


@pytest.mark.parametrize("text", ["मदद", "help", "Help me"])
def test_help_phrases_are_recognised(text: str):
    assert classify_global(text) is GlobalIntent.HELP


@pytest.mark.parametrize("text", ["कौन देखता है?", "who sees this", "privacy"])
def test_privacy_phrases_are_recognised(text: str):
    assert classify_global(text) is GlobalIntent.PRIVACY


def test_delete_outranks_stop_when_both_appear():
    assert classify_global("stop and delete my data") is GlobalIntent.DELETE


@pytest.mark.parametrize("text", ["रिया, 5 कहाँ से आया?", "Namaste", ""])
def test_ordinary_speech_is_not_a_global_intent(text: str):
    assert classify_global(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("हाँ", True),
        ("हां", True),
        ("जी हाँ", True),
        ("हाँ, मिटाओ", True),
        ("Yes", True),
        ("ok", True),
        ("नहीं", False),
        ("नही", False),
        ("no", False),
        ("हाँ नहीं", False),
        ("शायद", None),
        ("", None),
    ],
)
def test_yes_no(text: str, expected: bool | None):
    assert parse_yes_no(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hindi", "hi"),
        ("हिंदी", "hi"),
        ("हिन्दी में", "hi"),
        ("English", "en"),
        ("अंग्रेजी", "en"),
        ("इंग्लिश", "en"),
        ("French", None),
    ],
)
def test_language_choice(text: str, expected: str | None):
    assert parse_language(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", "1"),
        ("दो", "2"),
        ("तीसरी कक्षा", "3"),
        ("class 2", "2"),
        ("२", "2"),
        ("2 और 3 मिली-जुली", "multi"),
        ("mixed", "multi"),
        ("1 and 2", "multi"),
        ("कोई नहीं", None),
        ("7", None),
    ],
)
def test_grade_choice(text: str, expected: str | None):
    assert parse_grade(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "सहमति वापस",
        "मेरी सहमति वापस लो।",
        "Withdraw consent",
        "I want to withdraw my consent",
        "revoke consent",
    ],
)
def test_consent_withdrawal_phrases_are_recognised(text: str):
    assert classify_global(text) is GlobalIntent.WITHDRAW_CONSENT


def test_delete_outranks_withdrawal_when_both_appear():
    assert classify_global("withdraw consent and delete my data") is GlobalIntent.DELETE


def test_a_bare_consent_question_is_not_a_withdrawal():
    assert classify_global("what is consent") is None


@pytest.mark.parametrize(
    "text",
    [
        "मेरा डेटा भेजो",
        "मेरा डेटा भेजो।",
        "मेरा डाटा भेजो",
        "Send me my data",
        "please send me my data",
        "export my data",
    ],
)
def test_export_phrases_are_recognised(text: str):
    assert classify_global(text) is GlobalIntent.EXPORT


def test_delete_outranks_export_when_both_appear():
    assert classify_global("send me my data and then delete my data") is GlobalIntent.DELETE


def test_a_sentence_that_merely_mentions_data_is_not_an_export():
    assert classify_global("my data is in the register") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plan", MenuIntent.PLAN),
        ("Plan for tomorrow", MenuIntent.PLAN),
        ("प्लान", MenuIntent.PLAN),
        ("reflect", MenuIntent.REFLECT),
        ("रिफ्लेक्ट", MenuIntent.REFLECT),
        ("mirror", MenuIntent.MIRROR),
        ("मिरर", MenuIntent.MIRROR),
    ],
)
def test_menu_words_are_recognised(text: str, expected: MenuIntent):
    assert classify_menu(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "umm",
        # a long sentence that merely uses the word is lesson content, not a command
        "tomorrow I will teach the plan of the village and how to draw a mirror image",
    ],
)
def test_ordinary_or_long_utterances_are_not_menu_commands(text: str):
    assert classify_menu(text) is None
