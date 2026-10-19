import pytest

from app.content.copy import render
from app.core.reflect import (
    ReflectBrief,
    Reflected,
    ReflectionDraft,
    Reflector,
    ReflectRequest,
    ReflectUnavailableError,
    ReflectWriterError,
)
from app.core.speech_budget import REFLECT_BUDGET_SECONDS, fits

GOOD = ReflectionDraft(
    strength="You waited before helping Meena, and she found the tens herself.",
    next_step="Next time, ask Riya how she got 45 before saying anything.",
    model_example="Try: 'Show me with the sticks what you did.'",
)
HARSH = ReflectionDraft(
    strength="You tried.",
    next_step="Your answer to Riya was wrong and the lesson was bad.",
    model_example="Say it properly.",
)
REQUEST = ReflectRequest(notes="Meena was quiet, Riya said 45", lang="en", move_id=2)


class ScriptedWriter:
    def __init__(self, *drafts: ReflectionDraft | Exception) -> None:
        self.drafts = list(drafts)
        self.briefs: list[ReflectBrief] = []

    async def write(self, brief: ReflectBrief) -> ReflectionDraft:
        self.briefs.append(brief)
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return draft


async def test_a_kind_draft_is_spoken_strength_then_next_step_then_example():
    outcome = await Reflector(ScriptedWriter(GOOD)).reflect(REQUEST)

    assert isinstance(outcome, Reflected)
    assert outcome.draft == GOOD
    assert outcome.text.index(GOOD.strength) < outcome.text.index(GOOD.next_step)
    assert outcome.text.index(GOOD.next_step) < outcome.text.index(GOOD.model_example)
    assert render("reflect_label_strength", "en") in outcome.text
    assert fits(outcome.text, REFLECT_BUDGET_SECONDS)


async def test_a_harsh_draft_is_regenerated_and_the_writer_is_told_which_words_to_avoid():
    writer = ScriptedWriter(HARSH, GOOD)
    outcome = await Reflector(writer).reflect(REQUEST)

    assert outcome.draft == GOOD
    assert writer.briefs[0].avoid == ()
    assert set(writer.briefs[1].avoid) == {"wrong", "bad"}


async def test_a_coach_that_stays_harsh_is_never_spoken():
    with pytest.raises(ReflectUnavailableError):
        await Reflector(ScriptedWriter(HARSH, HARSH)).reflect(REQUEST)


@pytest.mark.parametrize("blank_field", ["strength", "next_step", "model_example"])
async def test_a_draft_with_an_empty_part_is_retried(blank_field: str):
    broken = ReflectionDraft(**{**GOOD.__dict__, blank_field: "  "})
    writer = ScriptedWriter(broken, GOOD)

    outcome = await Reflector(writer).reflect(REQUEST)

    assert outcome.draft == GOOD
    assert len(writer.briefs) == 2


async def test_an_overlong_reflection_is_retried_with_a_request_to_be_shorter():
    wordy = ReflectionDraft("s " * 300, "n " * 300, "m " * 300)
    writer = ScriptedWriter(wordy, GOOD)

    await Reflector(writer).reflect(REQUEST)

    assert [b.shorter for b in writer.briefs] == [False, True]


async def test_a_model_failure_is_retried_once_then_given_up():
    assert (
        await Reflector(ScriptedWriter(ReflectWriterError("x"), GOOD)).reflect(REQUEST)
    ).draft == GOOD
    with pytest.raises(ReflectUnavailableError):
        await Reflector(ScriptedWriter(ReflectWriterError("x"), ReflectWriterError("y"))).reflect(
            REQUEST
        )


async def test_phone_numbers_in_the_teachers_notes_never_reach_the_writer():
    writer = ScriptedWriter(GOOD)
    await Reflector(writer).reflect(ReflectRequest("call 9876543210 after class", "en", 1))

    assert "9876543210" not in writer.briefs[0].notes


async def test_the_reflection_is_spoken_in_the_requested_language():
    outcome = await Reflector(ScriptedWriter(GOOD)).reflect(ReflectRequest("नोट्स", "hi", 1))

    assert render("reflect_label_strength", "hi") in outcome.text
