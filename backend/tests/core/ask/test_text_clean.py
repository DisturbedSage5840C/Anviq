import pytest

from app.core.ask.text_clean import clean_text


@pytest.mark.parametrize(
    ("garbled", "clean"),
    [
        ("बच््चोों", "बच्चों"),  # doubled virama and doubled matra/anusvara from PDF extraction
        ("शिक्षाा", "शिक्षा"),
        ("पढ़़ना", "पढ़ना"),  # doubled nukta
        ("कककक", "कककक"),  # repeated base letters are not marks; left alone
    ],
)
def test_repeated_identical_devanagari_marks_collapse_to_one(garbled: str, clean: str):
    assert clean_text(garbled) == clean


def test_text_that_is_already_correct_is_unchanged():
    text = "बच्चों को पढ़ना सिखाएँ। Grade 2, page 14: फ़र्क़।"

    assert clean_text(text) == text


def test_different_marks_next_to_each_other_are_kept():
    assert clean_text("किंतु") == "किंतु"  # i-matra then anusvara are two different marks
    assert clean_text("हैं") == "हैं"


def test_text_is_put_in_composed_form():
    assert clean_text("e\u0301") == "\u00e9"


def test_joiners_that_shape_conjuncts_are_preserved():
    text = "क्‍ष"  # zero-width joiner is meaningful in Devanagari

    assert clean_text(text) == text


def test_english_text_passes_through():
    assert clean_text("Teach place value using bundles of ten.") == (
        "Teach place value using bundles of ten."
    )


def test_cleaning_twice_gives_the_same_result():
    once = clean_text("बच््चोों")

    assert clean_text(once) == once
