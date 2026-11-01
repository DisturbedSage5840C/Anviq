import pytest

from app.content.copy import render
from app.core.mirror import Growth, growth_label
from app.core.self_rating import compare, parse_rating, rating_prompt


@pytest.mark.parametrize(
    ("text", "growth"),
    [
        ("1", Growth.SPROUT),
        ("2", Growth.LEAF),
        ("3", Growth.TREE),
        (" 2 ", Growth.LEAF),
        ("१", Growth.SPROUT),
        ("३", Growth.TREE),
        ("🌱", Growth.SPROUT),
        ("🌿", Growth.LEAF),
        ("🌳", Growth.TREE),
        ("🌿\n", Growth.LEAF),
        ("sprout", Growth.SPROUT),
        (" Leaf ", Growth.LEAF),
        ("TREE", Growth.TREE),
        ("अंकुर", Growth.SPROUT),
        ("पत्ती", Growth.LEAF),
        ("पेड़", Growth.TREE),
        ("\u092a\u0947\u0921\u093c", Growth.TREE),  # ड + nukta, as some keyboards type it
        ("\u092a\u0947\u095c", Growth.TREE),  # the single precomposed ड़
    ],
)
def test_a_digit_a_growth_word_or_an_old_plant_is_a_rating(text: str, growth: Growth) -> None:
    assert parse_rating(text) is growth


@pytest.mark.parametrize(
    "text",
    [
        "",
        "0",
        "4",
        "12",
        "1 2",
        "2 bachche",
        "How did you get 28?",
        "🌿🌳",
        "two",
        "९",
        "leaf tree",
        "treehouse",
    ],
)
def test_anything_else_is_not_a_rating(text: str) -> None:
    assert parse_rating(text) is None


def test_the_prompt_asks_for_a_rating_in_the_teachers_language() -> None:
    assert rating_prompt("en") == render("self_rating_prompt", "en")
    assert rating_prompt("hi") == render("self_rating_prompt", "hi")
    for lang in ("en", "hi"):
        assert all(growth_label(level, lang) in rating_prompt(lang) for level in Growth)


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_agreeing_with_the_coach_is_said_plainly(lang: str) -> None:
    text = compare(Growth.LEAF, Growth.LEAF, lang)

    leaf = growth_label(Growth.LEAF, lang)
    assert text.count(leaf) == 2
    assert text == render("self_rating_same", lang).format(mine=leaf, coach=leaf)


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_rating_above_the_coach_points_to_what_could_lift_it(lang: str) -> None:
    text = compare(Growth.TREE, Growth.SPROUT, lang)

    assert text == render("self_rating_higher", lang).format(
        mine=growth_label(Growth.TREE, lang), coach=growth_label(Growth.SPROUT, lang)
    )


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_rating_below_the_coach_is_kind_about_it(lang: str) -> None:
    text = compare(Growth.SPROUT, Growth.TREE, lang)

    assert text == render("self_rating_lower", lang).format(
        mine=growth_label(Growth.SPROUT, lang), coach=growth_label(Growth.TREE, lang)
    )


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_a_comparison_line_carries_no_emoji(lang: str) -> None:
    for mine in Growth:
        for coach in Growth:
            assert not any(ord(char) > 0x1F000 for char in compare(mine, coach, lang))
