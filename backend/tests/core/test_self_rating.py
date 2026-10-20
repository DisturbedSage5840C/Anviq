import pytest

from app.content.copy import render
from app.core.mirror import Growth
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
    ],
)
def test_a_bare_digit_or_plant_is_a_rating(text: str, growth: Growth) -> None:
    assert parse_rating(text) is growth


@pytest.mark.parametrize(
    "text",
    ["", "0", "4", "12", "1 2", "2 bachche", "How did you get 28?", "🌿🌳", "two", "९"],
)
def test_anything_else_is_not_a_rating(text: str) -> None:
    assert parse_rating(text) is None


def test_the_prompt_asks_for_a_rating_in_the_teachers_language() -> None:
    assert rating_prompt("en") == render("self_rating_prompt", "en")
    assert rating_prompt("hi") == render("self_rating_prompt", "hi")
    assert all(plant.value in rating_prompt("en") for plant in Growth)


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_agreeing_with_the_coach_is_said_plainly(lang: str) -> None:
    text = compare(Growth.LEAF, Growth.LEAF, lang)

    assert text.count("🌿") == 2
    assert text == render("self_rating_same", lang).format(mine="🌿", coach="🌿")


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_rating_above_the_coach_points_to_what_could_lift_it(lang: str) -> None:
    text = compare(Growth.TREE, Growth.SPROUT, lang)

    assert text == render("self_rating_higher", lang).format(mine="🌳", coach="🌱")


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_rating_below_the_coach_is_kind_about_it(lang: str) -> None:
    text = compare(Growth.SPROUT, Growth.TREE, lang)

    assert text == render("self_rating_lower", lang).format(mine="🌱", coach="🌳")
