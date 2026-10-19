from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.children.personas import ChildState
from app.core.coach import (
    Coach,
    CoachRequest,
    CoachUnavailableError,
    _CoachOut,
    nudge_text,
)
from app.core.rubric import MOVES, load_rubric
from app.llm.client import LLMError, SystemBlock

REQUEST = CoachRequest(
    move_id=2,
    week="A",
    lang="en",
    child_name="Riya",
    child_text="45",
    teacher_text="No, that is wrong.",
    child_state=ChildState.CONFUSED,
)


def out(
    met: dict[str, str | None],
    *,
    phrasing: str = "Riya, where did the 5 come from?",
    feedback: str = "You corrected before she explained.",
) -> _CoachOut:
    """A model reply; `met` maps criterion id to its evidence quote, or None when not met."""
    return _CoachOut.model_validate(
        {
            "criteria": [
                {"id": cid, "met": evidence is not None, "evidence": evidence or ""}
                for cid, evidence in met.items()
            ],
            "better_phrasing": {"hi": "रिया, 5 कहाँ से आया?", "en": phrasing},
            "one_line_feedback": {"hi": "आपने पहले सुधारा।", "en": feedback},
        }
    )


class Scripted:
    """Stands in for the model: returns the scripted replies in order, records the prompts."""

    def __init__(self, *replies: _CoachOut | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self,
        purpose: str,
        *,
        model: str,
        system: Sequence[SystemBlock],
        messages: Sequence[Mapping[str, Any]],
        schema: type[BaseModel],
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> Any:
        self.calls.append({"system": system, "messages": messages, "model": model})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


ALL_MET = {"C1": "q", "C2": "q", "C3": "q", "C4": "q"}
NONE_MET = {"C1": None, "C2": None, "C3": None, "C4": None}


async def test_scores_each_criterion_with_evidence():
    coach = Coach(Scripted(out({"C1": None, "C2": "explain", "C3": None, "C4": None})), "m")
    verdict = await coach.score(REQUEST)
    assert dict(verdict.criteria) == {"C1": False, "C2": True, "C3": False, "C4": False}
    assert verdict.met_count == 1
    assert verdict.evidence == {"C2": "explain"}
    assert verdict.better_phrasing == "Riya, where did the 5 come from?"
    assert not verdict.advances_child


async def test_met_without_evidence_counts_as_not_met():
    reply = _CoachOut.model_validate(
        {
            "criteria": [{"id": c, "met": True, "evidence": " "} for c in ("C1", "C2", "C3", "C4")],
            "better_phrasing": {"hi": "क", "en": "a"},
            "one_line_feedback": {"hi": "क", "en": "Nice."},
        }
    )
    verdict = await Coach(Scripted(reply), "m").score(REQUEST)
    assert verdict.met_count == 0


async def test_wrong_criteria_ids_are_retried_then_rejected():
    bad = out({"C1": "q", "C9": "q"})
    scripted = Scripted(bad, bad)
    with pytest.raises(CoachUnavailableError):
        await Coach(scripted, "m").score(REQUEST)
    assert len(scripted.calls) == 2


async def test_harsh_feedback_is_regenerated_once():
    harsh = out(NONE_MET, feedback="That was a bad question.")
    kind = out(NONE_MET, feedback="Try asking how she got it.")
    scripted = Scripted(harsh, kind)
    verdict = await Coach(scripted, "m").score(REQUEST)
    assert verdict.feedback == "Try asking how she got it."
    assert not verdict.fell_back
    assert "harsh" in str(scripted.calls[1]["messages"])


async def test_harsh_twice_falls_back_to_generic_kind_copy():
    harsh = out(NONE_MET, feedback="Poor effort.")
    verdict = await Coach(Scripted(harsh, harsh), "m").score(REQUEST)
    assert verdict.fell_back
    assert verdict.better_phrasing == ""
    assert "Good try" in verdict.feedback


async def test_feedback_is_cut_to_two_sentences():
    long = out(NONE_MET, feedback="One. Two. Three. Four.")
    verdict = await Coach(Scripted(long), "m").score(REQUEST)
    assert verdict.feedback == "One. Two."


async def test_model_failure_is_reported_without_detail():
    with pytest.raises(CoachUnavailableError) as err:
        await Coach(Scripted(LLMError("boom secret")), "m").score(REQUEST)
    assert "secret" not in str(err.value)


async def test_hindi_request_gets_hindi_text():
    request = CoachRequest(**{**REQUEST.__dict__, "lang": "hi"})
    verdict = await Coach(Scripted(out(NONE_MET)), "m").score(request)
    assert verdict.better_phrasing == "रिया, 5 कहाँ से आया?"


async def test_prompt_carries_rubric_examples_and_wraps_teacher_words():
    scripted = Scripted(out(NONE_MET))
    await Coach(scripted, "m").score(REQUEST)
    call = scripted.calls[0]
    assert call["system"][0].cache
    prompt = call["system"][0].text
    assert "Use the wrong answer" in prompt and "C4" in prompt and "Walk us through" in prompt
    user = call["messages"][0]["content"]
    assert "<teacher_utterance>No, that is wrong.</teacher_utterance>" in user


async def test_weak_criterion_is_decided_by_majority_of_three():
    first = out({"C1": "q", "C2": "q", "C3": "q", "C4": None})
    no = out({"C1": "q", "C2": "q", "C3": None, "C4": None})
    coach = Coach(Scripted(first, no, no), "m", vote_on=frozenset({"2:C3"}))
    verdict = await coach.score(REQUEST)
    assert verdict.criteria["C3"] is False
    assert "C3" not in verdict.evidence
    assert verdict.criteria["C1"] is True  # not a voted criterion: the first sample stands


async def test_majority_can_confirm_a_criterion():
    yes = out({"C1": "q", "C2": "q", "C3": "yes quote", "C4": None})
    no = out({"C1": "q", "C2": "q", "C3": None, "C4": None})
    coach = Coach(Scripted(no, yes, yes), "m", vote_on=frozenset({"2:C3"}))
    verdict = await coach.score(REQUEST)
    assert verdict.criteria["C3"] is True
    assert verdict.evidence["C3"] == "yes quote"


async def test_no_extra_samples_when_no_voted_criterion_applies():
    scripted = Scripted(out(NONE_MET))
    await Coach(scripted, "m", vote_on=frozenset({"1:C1"})).score(REQUEST)
    assert len(scripted.calls) == 1


def test_good_turn_gets_only_a_thumbs_up_and_never_a_number():
    verdict_good = _verdict({"C1": True, "C2": True, "C3": False, "C4": False})
    assert nudge_text(verdict_good, "en") == "👍"


def test_weak_turn_gets_emoji_feedback_and_one_phrasing_without_digits():
    text = nudge_text(_verdict({"C1": False, "C2": False, "C3": False, "C4": False}), "en")
    assert text.startswith("🌱") and "You could say: Try this." in text
    assert not any(ch.isdigit() for ch in text)


def test_every_move_has_a_rubric_with_binary_criteria_and_examples():
    for move_id in MOVES:
        rubric = load_rubric(move_id)
        assert 3 <= len(rubric.criteria) <= 4
        assert len(rubric.examples) >= 6
        ids = set(rubric.criterion_ids)
        assert all(example.met <= ids for example in rubric.examples)


def test_moves_one_and_two_have_six_positive_and_six_negative_examples():
    for move_id in (1, 2):
        rubric = load_rubric(move_id)
        positive = [e for e in rubric.examples if len(e.met) >= 2]
        negative = [e for e in rubric.examples if len(e.met) < 2]
        assert len(positive) >= 6 and len(negative) >= 6


def test_unknown_move_is_an_error():
    with pytest.raises(ValueError):
        load_rubric(7)


def _verdict(criteria: dict[str, bool]):
    from app.core.coach import CoachVerdict

    return CoachVerdict(2, criteria, {}, "Try this.", "Good try.")
