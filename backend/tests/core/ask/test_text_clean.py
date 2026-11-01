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


def test_the_mis_mapped_running_header_glyph_is_repaired_to_module():
    assert clean_text("मॉ\u0120ूल 3") == "मॉड्यूल 3"


@pytest.mark.parametrize(
    ("ligature", "letters"),
    [("\ufb01", "fi"), ("\ufb02", "fl"), ("\ufb00", "ff"), ("\ufb03", "ffi"), ("\ufb04", "ffl")],
)
def test_latin_ligature_glyphs_become_plain_letters(ligature: str, letters: str):
    assert clean_text(f"of{ligature}ce") == f"of{letters}ce"


def test_the_reprint_stamp_line_is_removed_but_the_text_around_it_stays():
    page = "First line of the lesson.\nReprint 2026-27\nSecond line of the lesson.\n"

    assert clean_text(page) == "First line of the lesson.\nSecond line of the lesson.\n"


def test_a_reprint_stamp_with_other_years_or_spacing_is_removed():
    assert clean_text("a\n  Reprint 2025-26  \nb") == "a\nb"


def test_the_word_reprint_inside_a_sentence_is_kept():
    text = "The publisher will reprint 2026-27 copies of the book."

    assert clean_text(text) == text
