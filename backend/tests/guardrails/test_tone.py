import pytest

from app.guardrails.tone import harsh_terms


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("That was wrong.", ("wrong",)),
        ("Your lesson was BAD and lazy", ("bad", "lazy")),
        ("यह जवाब गलत है", ("गलत",)),
        ("पाठ बेकार रहा", ("बेकार",)),
    ],
)
def test_harsh_words_are_found_in_either_language(text: str, expected: tuple[str, ...]):
    assert harsh_terms(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "You gave each child time to think. Next, ask 'how do you know?'",
        "बच्चों को सोचने का समय दिया। अगली बार पूछिए: कैसे पता?",
        "badges and wrongdoing are different words",  # whole words only
        "",
    ],
)
def test_kind_or_empty_text_has_no_harsh_words(text: str):
    assert harsh_terms(text) == ()


def test_a_word_is_reported_once_however_often_it_appears():
    assert harsh_terms("bad, so bad, truly bad") == ("bad",)


def test_hindi_words_do_not_match_inside_longer_hindi_words():
    # "गलती" (a mistake, said gently) must not trip the "गलत" rule
    assert harsh_terms("गलती से भी सीख मिलती है") == ()
