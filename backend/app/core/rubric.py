"""The six moves' rubrics, loaded from `app/content/rubrics/move_0N.toml`.

A rubric is binary criteria (plan section 3.2): each is yes or no, and the coach must quote
evidence for every yes. Labelled examples double as few-shot prompts and as gold-set seeds.
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

RUBRIC_DIR = Path(__file__).parents[1] / "content" / "rubrics"
MOVES = range(1, 7)


@dataclass(frozen=True)
class Criterion:
    id: str
    text: str


@dataclass(frozen=True)
class Example:
    text: str
    met: frozenset[str]


@dataclass(frozen=True)
class Rubric:
    move_id: int
    title_en: str
    title_hi: str
    status: str  # "draft" until Vansh and the mentor have reviewed it
    criteria: tuple[Criterion, ...]
    examples: tuple[Example, ...]

    @property
    def criterion_ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.criteria)


@cache
def load_rubric(move_id: int) -> Rubric:
    if move_id not in MOVES:
        raise ValueError(f"no such move: {move_id}")
    with (RUBRIC_DIR / f"move_{move_id:02d}.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    return Rubric(
        move_id=raw["move_id"],
        title_en=raw["title_en"],
        title_hi=raw["title_hi"],
        status=raw["status"],
        criteria=tuple(Criterion(c["id"], c["text"]) for c in raw["criteria"]),
        examples=tuple(Example(e["text"], frozenset(e["met"])) for e in raw["examples"]),
    )
