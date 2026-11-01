"""Literacy: reading and spelling problems and the misconceptions a child shows on them."""

import random

import pytest

from app.core.children.problem import Kind, Problem
from app.core.children.registry import (
    ALL_RULES,
    RULES_BY_ID,
    TOPIC_IDS,
    problem_for,
    rules_for_topic,
)
from app.core.topics import load_topics

LITERACY_TOPICS = (
    "LIT.G1.LETTER_SOUND",
    "LIT.G1.BLEND",
    "LIT.G2.SIGHT_WORDS",
    "LIT.G3.SPELL_SOUND",
    "LIT.G4.SPELL_PLURAL",
    "LIT.G5.SPELL_SUFFIX",
)
LITERACY_RULE_PREFIXES = ("LIT", "SPELL")


def _read(word: str) -> Problem:
    return Problem(Kind.READ_WORD, text=word)


def _spell(word: str) -> Problem:
    return Problem(Kind.SPELL_WORD, text=word)


@pytest.mark.parametrize(
    ("problem", "answer"),
    [(_read("bed"), "bed"), (_spell("running"), "running"), (_read("बकरी"), "बकरी")],
)
def test_the_correct_answer_to_a_word_problem_is_the_word(problem: Problem, answer: str):
    assert problem.correct_answer() == answer


def test_the_statement_names_the_word_and_the_task():
    assert "bed" in _read("bed").statement() and "read" in _read("bed").statement()
    assert "running" in _spell("running").statement()


@pytest.mark.parametrize(
    ("rule_id", "problem", "child_says"),
    [
        ("LIT.BD_REVERSAL", _read("bed"), "deb"),
        ("LIT.BV_SWAP_HI", _read("बकरी"), "वकरी"),
        ("LIT.DROP_FINAL_SOUND", _read("cat"), "ca"),
        ("LIT.VOWEL_SWAP", _read("cat"), "cet"),
        ("LIT.WORD_REVERSAL", _read("was"), "saw"),
        ("LIT.SHAPE_GUESS", _read("what"), "want"),
        ("SPELL.BY_SOUND", _spell("friend"), "frend"),
        ("SPELL.PLURAL_Y", _spell("babies"), "babys"),
        ("SPELL.DOUBLE_DROP", _spell("running"), "runing"),
        ("SPELL.SILENT_E_KEPT", _spell("hoping"), "hopeing"),
    ],
)
def test_each_literacy_rule_makes_its_one_mistake(rule_id: str, problem: Problem, child_says: str):
    result = RULES_BY_ID[rule_id].run(problem)

    assert result.answer == child_says
    assert result.correct_answer == problem.text
    assert result.answer != result.correct_answer
    assert result.steps


def test_a_literacy_rule_does_not_apply_to_a_word_it_cannot_misread():
    assert not RULES_BY_ID["LIT.BD_REVERSAL"].applies(_read("cat"))
    assert not RULES_BY_ID["SPELL.PLURAL_Y"].applies(_spell("friend"))
    assert not RULES_BY_ID["LIT.BD_REVERSAL"].applies(Problem(Kind.ADD, 2, 3))


def test_a_rule_refuses_a_word_it_does_not_apply_to():
    with pytest.raises(ValueError, match="does not apply"):
        RULES_BY_ID["SPELL.PLURAL_Y"].run(_spell("friend"))


@pytest.mark.parametrize("topic_id", LITERACY_TOPICS)
def test_every_literacy_topic_has_rules_and_a_topic_entry(topic_id: str):
    assert topic_id in TOPIC_IDS
    assert rules_for_topic(topic_id)
    assert topic_id in {t.id for t in load_topics()}


def test_literacy_topics_are_marked_as_literacy_and_cover_classes_one_to_five():
    topics = load_topics()
    literacy = [t for t in topics if t.subject == "literacy"]

    assert {t.id for t in literacy} == set(LITERACY_TOPICS)
    assert {t.grade for t in literacy} == {1, 2, 3, 4, 5}
    assert all(t.subject == "numeracy" for t in topics if t not in literacy)


def test_no_framework_reference_is_invented_for_literacy_topics():
    literacy = [t for t in load_topics() if t.subject == "literacy"]

    assert all(t.nipun_lo == "" and t.nishtha_ref == "" for t in literacy)


@pytest.mark.parametrize(
    "rule_id",
    sorted(r.id for r in ALL_RULES if r.id.startswith(LITERACY_RULE_PREFIXES)),
)
def test_generated_word_problems_always_trigger_the_rule(rule_id: str):
    rule = RULES_BY_ID[rule_id]
    rng = random.Random(11)

    for _ in range(25):
        problem = problem_for(rule, rng)
        assert problem.text
        assert rule.applies(problem)
        assert rule.run(problem).answer != problem.correct_answer()


def test_every_literacy_rule_is_reviewable_by_a_teacher():
    rules = [r for r in ALL_RULES if r.id.startswith(LITERACY_RULE_PREFIXES)]

    assert len(rules) == 10
    assert all(r.source and r.summary and r.grades for r in rules)
