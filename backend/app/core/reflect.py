"""Reflect: after the lesson, say one strength, one next step and a line the teacher could use.

Plan section 4.9. The model drafts, we check: every part present, no harsh words about the
teacher's practice, and no more than 45 seconds of speech. A failed check sends the writer back
once, told what to avoid; a coach that is still harsh, long or broken is never spoken, the caller
gets `ReflectUnavailableError` instead.
"""

from dataclasses import dataclass
from typing import Protocol

from app.content.copy import render
from app.core.speech_budget import REFLECT_BUDGET_SECONDS, fits
from app.guardrails.pii import scrub
from app.guardrails.tone import harsh_terms

MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class ReflectionDraft:
    strength: str
    next_step: str
    model_example: str

    def parts(self) -> tuple[str, str, str]:
        return (self.strength, self.next_step, self.model_example)


@dataclass(frozen=True)
class ReflectRequest:
    notes: str
    lang: str
    move_id: int


@dataclass(frozen=True)
class ReflectBrief:
    """Everything the writer is given. Contains only scrubbed text."""

    notes: str
    lang: str
    move_id: int
    avoid: tuple[str, ...]  # harsh words a previous draft used
    shorter: bool  # a previous draft ran past the speaking budget


@dataclass(frozen=True)
class Reflected:
    draft: ReflectionDraft
    text: str


class ReflectWriterError(Exception):
    """The model call failed or returned something unreadable."""


class ReflectUnavailableError(Exception):
    """No acceptable reflection after the allowed attempts."""


class ReflectionWriter(Protocol):
    async def write(self, brief: ReflectBrief) -> ReflectionDraft: ...


def render_reflection(draft: ReflectionDraft, lang: str) -> str:
    labelled = zip(
        ("reflect_label_strength", "reflect_label_next", "reflect_label_example"),
        draft.parts(),
        strict=True,
    )
    return "\n\n".join(f"{render(key, lang)}: {part}" for key, part in labelled)


class Reflector:
    def __init__(self, writer: ReflectionWriter) -> None:
        self._writer = writer

    async def reflect(self, request: ReflectRequest) -> Reflected:
        notes = scrub(request.notes)
        avoid: tuple[str, ...] = ()
        shorter = False
        for _ in range(MAX_ATTEMPTS):
            brief = ReflectBrief(notes, request.lang, request.move_id, avoid, shorter)
            try:
                draft = await self._writer.write(brief)
            except ReflectWriterError:
                continue
            if not all(part.strip() for part in draft.parts()):
                continue
            harsh = harsh_terms(" ".join(draft.parts()))
            if harsh:
                avoid = harsh
                continue
            text = render_reflection(draft, request.lang)
            if fits(text, REFLECT_BUDGET_SECONDS):
                return Reflected(draft, text)
            shorter = True
        raise ReflectUnavailableError(f"no usable reflection after {MAX_ATTEMPTS} tries")
