import pytest

from app.content.copy import render
from app.core.planner import (
    AskBack,
    Misconception,
    PlanBrief,
    Planned,
    Planner,
    PlanQuestion,
    PlanRequest,
    PlanUnavailableError,
    PlanWriterError,
    Resolved,
    Unsure,
)
from app.core.speech_budget import PLAN_BUDGET_SECONDS, fits

TOPIC = "NUM.G2.SUB.REGROUP"
RIYA = Misconception(child="Riya", answer="45", how="took the smaller digit from the larger")
GOOD = (
    PlanQuestion("Subtract 17 from 52 and tell me how.", "Riya: 45", "Ask where the 5 came from"),
    PlanQuestion(
        "Riya says 45, Aman says 35. Who is right?", "Aman: just knew", "Ask Aman to show"
    ),
    PlanQuestion("What can the tens help with?", "Meena: umm", "Wait before helping"),
)
REQUEST = PlanRequest(text="Tomorrow I teach subtraction", lang="en", move_id=2, week="A")


class FakeTopics:
    def __init__(self, match: Resolved | Unsure) -> None:
        self.match = match
        self.seen: list[str] = []

    async def resolve(self, text: str, lang: str) -> Resolved | Unsure:
        self.seen.append(text)
        return self.match


class FakeMisconceptions:
    async def for_topic(self, topic_id: str) -> tuple[Misconception, ...]:
        return (RIYA,) if topic_id == TOPIC else ()


class ScriptedWriter:
    """Hands back one scripted draft (or raises it) per call and remembers each brief."""

    def __init__(self, *drafts: tuple[PlanQuestion, ...] | Exception) -> None:
        self.drafts = list(drafts)
        self.briefs: list[PlanBrief] = []

    async def write(self, brief: PlanBrief) -> tuple[PlanQuestion, ...]:
        self.briefs.append(brief)
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return draft


def _planner(writer: ScriptedWriter, match: Resolved | Unsure | None = None) -> Planner:
    return Planner(FakeTopics(match or Resolved(TOPIC)), FakeMisconceptions(), writer)


async def test_unsure_topic_asks_the_teacher_back_without_calling_the_model():
    writer = ScriptedWriter()
    outcome = await _planner(writer, Unsure("Do you mean subtraction with borrowing?")).plan(
        REQUEST
    )

    assert outcome == AskBack("Do you mean subtraction with borrowing?")
    assert writer.briefs == []


async def test_a_good_draft_becomes_three_numbered_questions_and_an_invitation():
    outcome = await _planner(ScriptedWriter(GOOD)).plan(REQUEST)

    assert isinstance(outcome, Planned)
    assert outcome.topic_id == TOPIC
    assert outcome.questions == GOOD
    assert outcome.text.startswith("1) Subtract 17 from 52 and tell me how.")
    assert "3) What can the tens help with?" in outcome.text
    assert outcome.text.endswith(render("plan_cta", "en"))
    assert fits(outcome.text, PLAN_BUDGET_SECONDS)


async def test_the_writer_is_briefed_with_the_topics_misconceptions_and_the_move():
    writer = ScriptedWriter(GOOD)
    await _planner(writer).plan(REQUEST)

    brief = writer.briefs[0]
    assert (brief.topic_id, brief.move_id, brief.week, brief.lang) == (TOPIC, 2, "A", "en")
    assert brief.misconceptions == (RIYA,)
    assert brief.shorter is False


async def test_phone_numbers_are_scrubbed_before_any_model_sees_the_request():
    topics = FakeTopics(Resolved(TOPIC))
    writer = ScriptedWriter(GOOD)
    spoken = PlanRequest("call me on 9876543210 about subtraction", "en", 1, "A")

    await Planner(topics, FakeMisconceptions(), writer).plan(spoken)

    assert "9876543210" not in topics.seen[0]
    assert "9876543210" not in writer.briefs[0].request_text


@pytest.mark.parametrize("bad", [GOOD[:2], (*GOOD, GOOD[0]), ()])
async def test_a_draft_without_exactly_three_questions_is_retried_once(bad):
    writer = ScriptedWriter(bad, GOOD)
    outcome = await _planner(writer).plan(REQUEST)

    assert isinstance(outcome, Planned)
    assert len(writer.briefs) == 2


async def test_a_blank_question_makes_the_draft_invalid():
    blank = (GOOD[0], PlanQuestion("  ", "x", "y"), GOOD[2])
    writer = ScriptedWriter(blank, GOOD)
    outcome = await _planner(writer).plan(REQUEST)

    assert outcome.questions == GOOD  # type: ignore[union-attr]


async def test_an_overlong_plan_is_retried_with_a_request_to_be_shorter():
    wordy = tuple(PlanQuestion("q " * 400, "a", "b") for _ in range(3))
    writer = ScriptedWriter(wordy, GOOD)
    await _planner(writer).plan(REQUEST)

    assert [b.shorter for b in writer.briefs] == [False, True]


async def test_two_unusable_drafts_give_up_instead_of_sending_a_bad_plan():
    writer = ScriptedWriter(GOOD[:1], GOOD[:2])
    with pytest.raises(PlanUnavailableError):
        await _planner(writer).plan(REQUEST)


async def test_a_model_failure_on_the_first_try_is_retried():
    writer = ScriptedWriter(PlanWriterError("timeout"), GOOD)
    outcome = await _planner(writer).plan(REQUEST)

    assert isinstance(outcome, Planned)


async def test_a_model_that_keeps_failing_gives_up():
    writer = ScriptedWriter(PlanWriterError("down"), PlanWriterError("down"))
    with pytest.raises(PlanUnavailableError):
        await _planner(writer).plan(REQUEST)


async def test_the_plan_is_spoken_in_the_requested_language():
    outcome = await _planner(ScriptedWriter(GOOD)).plan(
        PlanRequest("कल घटाना पढ़ाना है", "hi", 1, "B")
    )
    assert isinstance(outcome, Planned)
    assert outcome.text.endswith(render("plan_cta", "hi"))
