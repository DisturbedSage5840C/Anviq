import pytest

from app.core.langid import Detection, Script, detect, wording_hint


@pytest.mark.parametrize(
    ("text", "script"),
    [
        ("बच्चे घटाना क्यों नहीं सीख पाते", Script.DEVANAGARI),
        ("শিশুরা কেন শেখে না", Script.BENGALI),
        ("ਬੱਚੇ ਕਿਉਂ ਨਹੀਂ ਸਿੱਖਦੇ", Script.GURMUKHI),
        ("குழந்தைகள் ஏன் கற்றுக்கொள்வதில்லை", Script.TAMIL),
        ("పిల్లలు ఎందుకు నేర్చుకోరు", Script.TELUGU),
        ("ಮಕ್ಕಳು ಏಕೆ ಕಲಿಯುವುದಿಲ್ಲ", Script.KANNADA),
        ("കുട്ടികൾ എന്തുകൊണ്ട് പഠിക്കുന്നില്ല", Script.MALAYALAM),
        ("બાળકો કેમ શીખતા નથી", Script.GUJARATI),
        ("ପିଲାମାନେ କାହିଁକି ଶିଖନ୍ତି ନାହିଁ", Script.ODIA),
        ("how do I teach subtraction", Script.LATIN),
    ],
)
def test_script_is_read_from_the_letters(text: str, script: Script):
    assert detect(text).script is script


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("haan ji", "hi"),
        ("nahi, aap batao", "hi"),
        ("bacche ghatana kyun nahi seekh paate", "hi"),
        ("mujhe lesson plan chahiye", "hi"),
        ("बच्चे घटाना क्यों नहीं सीख पाते", "hi"),
        ("मुझे पाठ योजना चाहिए", "hi"),
        ("मुलांना वजाबाकी का समजत नाही", "mr"),
        ("मला धडा समजावून सांगा आणि उदाहरण द्या", "mr"),
        ("குழந்தைகள் ஏன் கற்றுக்கொள்வதில்லை", "ta"),
        ("how do I teach subtraction to class two", "en"),
        ("yes please", "en"),
        ("what is place value", "en"),
        ("শিশুরা কেন শেখে না", "bn"),
    ],
)
def test_language_is_named_when_the_evidence_is_clear(text: str, language: str):
    assert detect(text).language == language


def test_code_mixed_hinglish_is_hindi_in_latin_letters():
    detection = detect("sir ye problem bacchon ko samajh nahi aa raha")
    assert (detection.script, detection.language) == (Script.LATIN, "hi")


def test_english_with_a_stray_hindi_word_stays_english():
    assert detect("my students call this jugaad but it works for subtraction").language == "en"


@pytest.mark.parametrize("text", ["", "   ", "123", "?!", "ok", "k", "\U0001f44d"])
def test_no_evidence_is_undetermined_not_guessed(text: str):
    assert detect(text).language == "und"


def test_the_two_word_ambiguity_of_ok_and_ji_is_resolved_only_by_other_words():
    assert detect("ji").language == "hi"
    assert detect("ok").language == "und"


def test_detection_is_a_frozen_value_with_a_confidence_between_zero_and_one():
    detection = detect("haan ji")
    assert isinstance(detection, Detection)
    assert 0.0 < detection.confidence <= 1.0
    with pytest.raises(AttributeError):
        detection.language = "en"  # type: ignore[misc]


def test_a_longer_run_of_evidence_is_more_confident_than_one_word():
    assert detect("haan ji bilkul aap theek keh rahe hain").confidence > detect("haan").confidence


def test_devanagari_digits_and_punctuation_do_not_change_the_script():
    assert detect("१ २ ३ क्या है?").script is Script.DEVANAGARI


def test_mixed_scripts_follow_the_majority_of_letters():
    assert detect("आप lesson plan बना सकते हैं").script is Script.DEVANAGARI


# --- wording_hint: what the model is told about how the teacher typed -----------------------------
@pytest.mark.parametrize(
    ("text", "hint"),
    [
        ("bacche ghatana kyun nahi seekh paate", "Hindi typed in English letters"),
        ("बच्चे घटाना क्यों नहीं सीख पाते", "Hindi"),
        ("मुलांना वजाबाकी का समजत नाही", "Marathi"),
        ("குழந்தைகளுக்கு கழித்தல் எப்படி கற்பிப்பது", "Tamil"),
    ],
)
def test_wording_hint_names_how_the_teacher_wrote(text: str, hint: str):
    assert wording_hint(detect(text)) == hint


@pytest.mark.parametrize("text", ["how do I teach subtraction to class two", "ok", "", "123"])
def test_wording_hint_is_silent_for_plain_english_and_for_no_evidence(text: str):
    assert wording_hint(detect(text)) is None
