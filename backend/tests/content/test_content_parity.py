"""The reviewed content in `content/` (YAML) and the copy the app loads (TOML) must not drift.

Vansh edits and reviews the YAML; the backend reads the TOML shipped in the image. Nothing else
connects them, so these tests do. The scenario bank is also run through the executable malrules, so
a wrong answer on either side shows up here and not in front of a teacher.
"""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

from app.content.copy import COPY_DIR, LANGS
from app.core.children.problem import Kind, Problem
from app.core.children.registry import _KIND_BY_TOPIC, RULES_BY_ID
from app.core.rubric import RUBRIC_DIR
from app.core.topics import TOPICS_FILE

CONTENT_DIR = Path(__file__).parents[3] / "content"
MOVES = range(1, 7)
SCENARIOS_PER_TOPIC = 3

pytestmark = pytest.mark.skipif(not CONTENT_DIR.is_dir(), reason="content/ is not checked out")


def _yaml(relative: str) -> dict:
    return yaml.safe_load((CONTENT_DIR / relative).read_text(encoding="utf-8"))


def _toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _reviewed_topics() -> list[dict]:
    return _yaml("topic_map.yaml")["topics"]


def _problem(topic_id: str, statement: str) -> Problem:
    kind = _KIND_BY_TOPIC[topic_id]
    numbers = [int(n) for n in re.findall(r"\d+", statement)]
    return Problem(kind, *numbers[: 1 if kind is Kind.WRITE_NUMBER else 2])


def _scenarios() -> list[tuple[str, dict]]:
    return [(t["id"], s) for t in _reviewed_topics() for s in t["scenarios"]]


def _scenario_id(value: str | dict) -> str:
    return value if isinstance(value, str) else str(value["problem"])[:24]


@pytest.mark.parametrize("move", MOVES)
def test_the_runtime_rubric_is_the_reviewed_rubric(move: int):
    name = f"move_{move:02d}"

    assert _toml(RUBRIC_DIR / f"{name}.toml") == _yaml(f"rubrics/{name}.yaml")


@pytest.mark.parametrize("lang", LANGS)
def test_every_reviewed_copy_line_is_what_the_app_says(lang: str):
    runtime = _toml(COPY_DIR / f"{lang}.toml")
    reviewed = _yaml(f"copy/{lang}.yaml")

    differing = [k for k, text in reviewed.items() if runtime.get(k, "").strip() != text.strip()]

    assert differing == []


def test_the_runtime_topics_are_the_reviewed_topics():
    runtime = {t["id"]: t for t in _toml(TOPICS_FILE)["topic"]}
    reviewed = {
        t["id"]: {k: v for k, v in t.items() if k != "scenarios"} for t in _reviewed_topics()
    }

    assert runtime == reviewed


def test_every_topic_has_its_scenarios():
    counts = {t["id"]: len(t["scenarios"]) for t in _reviewed_topics()}

    assert set(counts.values()) == {SCENARIOS_PER_TOPIC}


@pytest.mark.parametrize(("topic_id", "scenario"), _scenarios(), ids=_scenario_id)
@pytest.mark.parametrize("child", ["riya", "meena"])
def test_the_code_gives_a_child_the_answer_the_reviewed_bank_says(
    topic_id: str, scenario: dict, child: str
):
    if f"{child}_misconception" not in scenario:
        pytest.skip(f"{child} has no misconception in this scenario")
    rule = RULES_BY_ID[scenario[f"{child}_misconception"]]

    result = rule.run(_problem(topic_id, scenario["problem"]))

    assert topic_id in rule.topic_ids
    assert (result.answer, result.correct_answer) == (
        scenario[f"{child}_answer"],
        scenario["correct_answer"],
    )


@pytest.mark.parametrize(("topic_id", "scenario"), _scenarios(), ids=_scenario_id)
def test_aman_is_right_wherever_the_bank_gives_him_an_answer(topic_id: str, scenario: dict):
    if "aman_answer" not in scenario:
        pytest.skip("Aman has no answer in this scenario")

    assert scenario["aman_answer"] == _problem(topic_id, scenario["problem"]).correct_answer()
