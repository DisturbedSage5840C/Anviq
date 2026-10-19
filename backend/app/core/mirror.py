"""Mirror: on Day 14, set the teacher's Day 1 question beside today's and show the growth.

Plan section 3.5. Only transcripts are compared (the opt-in voice clip is a storage concern, see
`db/mirror_store.py`). The teacher sees 🌱 / 🌿 / 🌳 and words, never a number. Growth is
celebrated; a flat or lower Day 14 is met with encouragement, never a verdict.

`cycle_is_due` is where demo mode lives: with `demo_minutes` set, a "14-day" cycle lasts that many
minutes, so a judge can watch a whole Day 1 to Day 14 arc in one sitting.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from app.content.copy import render
from app.core.speech_budget import MIRROR_QUOTE_SECONDS, truncate_to_budget

CYCLE_LENGTH = timedelta(days=14)
LEAF_AT = 2  # criteria met for a 🌿
TREE_AT = 3  # criteria met for a 🌳


class Growth(StrEnum):
    SPROUT = "🌱"
    LEAF = "🌿"
    TREE = "🌳"


def growth_for(met_count: int) -> Growth:
    if met_count >= TREE_AT:
        return Growth.TREE
    if met_count >= LEAF_AT:
        return Growth.LEAF
    return Growth.SPROUT


@dataclass(frozen=True)
class MirrorTurn:
    """One teacher turn as scored by the coach: its scrubbed text and which criteria were met."""

    text: str
    criteria: Mapping[str, bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", MappingProxyType(dict(self.criteria)))

    @property
    def met_count(self) -> int:
        return sum(self.criteria.values())


@dataclass(frozen=True)
class MirrorDiff:
    first: MirrorTurn
    latest: MirrorTurn
    gained: tuple[str, ...]  # met now, not on Day 1
    kept: tuple[str, ...]  # met on both days
    open: tuple[str, ...]  # not met today: the next thing to grow

    @property
    def first_growth(self) -> Growth:
        return growth_for(self.first.met_count)

    @property
    def latest_growth(self) -> Growth:
        return growth_for(self.latest.met_count)


def compare(first: MirrorTurn, latest: MirrorTurn) -> MirrorDiff:
    ids = sorted({*first.criteria, *latest.criteria})
    met_before = {i for i in ids if first.criteria.get(i, False)}
    met_now = {i for i in ids if latest.criteria.get(i, False)}
    return MirrorDiff(
        first=first,
        latest=latest,
        gained=tuple(i for i in ids if i in met_now - met_before),
        kept=tuple(i for i in ids if i in met_now & met_before),
        open=tuple(i for i in ids if i not in met_now),
    )


def render_mirror(diff: MirrorDiff, lang: str) -> str:
    quote_first = truncate_to_budget(diff.first.text, MIRROR_QUOTE_SECONDS)
    quote_latest = truncate_to_budget(diff.latest.text, MIRROR_QUOTE_SECONDS)
    message = render("mirror_grew" if diff.gained else "mirror_steady", lang)
    return "\n".join(
        (
            f"{render('mirror_day1', lang)}: {quote_first}",
            f"{render('mirror_today', lang)}: {quote_latest}",
            "",
            f"{diff.first_growth} → {diff.latest_growth}",
            message,
        )
    )


def cycle_is_due(started_at: datetime, now: datetime, *, demo_minutes: int | None) -> bool:
    if demo_minutes is None:
        return now - started_at >= CYCLE_LENGTH
    if demo_minutes <= 0:
        raise ValueError(f"demo cycle must be a positive number of minutes, got {demo_minutes}")
    return now - started_at >= timedelta(minutes=demo_minutes)
