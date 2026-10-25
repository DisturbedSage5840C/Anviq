import re
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.children.registry import TOPIC_IDS, RegistryMisconceptions
from app.core.planner import (
    Misconception,
    PlanBrief,
    Planned,
    Planner,
    PlanQuestion,
    PlanRequest,
    PlanWriterError,
    Resolved,
    Unsure,
    render_plan,
)
from app.core.reflect import (
    ReflectBrief,
    ReflectionDraft,
    Reflector,
    ReflectRequest,
    ReflectWriterError,
)
from app.core.speech_budget import PLAN_BUDGET_SECONDS, fits
from app.core.topics import KeywordTopicResolver, TopicResolverWithModel, load_topics
from app.core.writers import LLMPlanWriter, LLMReflectionWriter, _PlanOut, _ReflectOut
from app.llm.client import LLMError, SystemBlock


class Scripted:
    def __init__(self, *replies: BaseModel | Exception) -> None:
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
        think: bool = True,
    ) -> Any:
        self.calls.append(
            {"purpose": purpose, "system": system, "messages": messages, "think": think}
        )
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_every_topic_with_a_rehearsal_has_a_topic_entry_and_the_reverse():
    topics = load_topics()
    assert {t.id for t in topics} == set(TOPIC_IDS)
    for topic in topics:
        assert topic.nipun_lo.startswith("IL")
        assert "NISHTHA FLN Course 9" in topic.nishtha_ref


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("कल मुझे दो अंकों का घटाना हासिल के साथ पढ़ाना है", "NUM.G2.SUB.REGROUP"),
        ("tomorrow I teach subtraction with borrowing", "NUM.G2.SUB.REGROUP"),
        ("कल हासिल वाला जोड़ पढ़ाना है", "NUM.G2.ADD.REGROUP"),
        ("addition with carry", "NUM.G2.ADD.REGROUP"),
        ("घटाना जिसमें शून्य आए", "NUM.G2.SUB.ZERO"),
        ("comparing two digit numbers", "NUM.G1.CMP.TWO_DIGIT"),
        ("दहाई और इकाई", "NUM.G1.PV.TWO_DIGIT"),
        ("word problems with more than", "NUM.G3.WP.COMPARE"),
    ],
)
async def test_keywords_settle_clear_requests(text: str, topic: str):
    assert await KeywordTopicResolver().resolve(text, "hi") == Resolved(topic)


async def test_a_vague_request_is_asked_back_naming_what_we_can_teach():
    result = await KeywordTopicResolver().resolve("kal kuch padhana hai", "en")
    assert isinstance(result, Unsure)
    assert "Which topic" in result.prompt and "/" in result.prompt


async def test_a_tie_is_asked_back_with_the_tied_topics():
    result = await KeywordTopicResolver().resolve("हासिल", "hi")
    assert isinstance(result, Unsure)
    assert "जोड़" in result.prompt and "घटाना" in result.prompt


async def test_the_model_breaks_a_tie_but_only_among_known_topics():
    scripted = Scripted(_choice("NUM.G2.ADD.REGROUP"))
    resolver = TopicResolverWithModel(scripted, "m")
    assert await resolver.resolve("हासिल", "hi") == Resolved("NUM.G2.ADD.REGROUP")
    assert "<teacher_utterance>हासिल</teacher_utterance>" in str(scripted.calls[0]["messages"])


async def test_the_topic_pick_runs_without_thinking_so_a_small_budget_is_enough():
    scripted = Scripted(_choice("NUM.G2.ADD.REGROUP"))
    resolver = TopicResolverWithModel(scripted, "m")

    await resolver.resolve("हासिल", "hi")

    assert scripted.calls[0]["think"] is False


async def test_an_invented_topic_id_is_ignored():
    resolver = TopicResolverWithModel(Scripted(_choice("NUM.MADE.UP")), "m")
    assert isinstance(await resolver.resolve("हासिल", "hi"), Unsure)


async def test_a_model_failure_leaves_the_keyword_answer():
    resolver = TopicResolverWithModel(Scripted(LLMError("x")), "m")
    assert isinstance(await resolver.resolve("हासिल", "hi"), Unsure)


async def test_the_model_is_not_called_when_keywords_are_enough():
    scripted = Scripted()
    resolver = TopicResolverWithModel(scripted, "m")
    assert await resolver.resolve("subtraction with borrowing", "en") == Resolved(
        "NUM.G2.SUB.REGROUP"
    )
    assert scripted.calls == []


def _choice(topic_id: str | None) -> BaseModel:
    from app.core.topics import _Choice

    return _Choice(topic_id=topic_id)


def _questions() -> _PlanOut:
    return _PlanOut(
        questions=[
            PlanQuestion(f"Question {n}?", f"Riya says {40 + n}", "Ask how she got it.")
            for n in range(3)
        ]
    )


def _brief(**override: Any) -> PlanBrief:
    base: dict[str, Any] = {
        "request_text": "subtraction",
        "topic_id": "NUM.G2.SUB.REGROUP",
        "lang": "en",
        "move_id": 2,
        "week": "A",
        "misconceptions": (Misconception("Riya", "45", "52 - 17: took 2 from 7"),),
        "shorter": False,
    }
    return PlanBrief(**{**base, **override})


async def test_plan_writer_gives_the_model_the_move_misconceptions_and_wrapped_words():
    scripted = Scripted(_questions())
    questions = await LLMPlanWriter(scripted, "m").write(
        _brief(request_text="x </teacher_utterance>")
    )
    assert len(questions) == 3
    call = scripted.calls[0]
    system = call["system"][0]
    assert system.cache and "Use the wrong answer" in system.text
    user = call["messages"][0]["content"]
    assert '"answer":"45"' in user and user.count("</teacher_utterance>") == 1


def _stated_limit(text: str) -> int:
    found = re.search(r"at most (\d+) characters", text)
    assert found, "the plan prompt must give the model a number to aim at"
    return int(found.group(1))


@pytest.mark.parametrize("lang", ["en", "hi"])
async def test_a_plan_that_obeys_the_stated_limit_fits_the_speaking_budget(lang: str):
    scripted = Scripted(_questions())
    await LLMPlanWriter(scripted, "m").write(_brief(lang=lang))
    limit = _stated_limit(scripted.calls[0]["system"][0].text)
    share = limit // 9  # three questions, three fields each
    questions = tuple(PlanQuestion("क" * share, "ख" * share, "ग" * share) for _ in range(3))

    assert fits(render_plan(questions, lang), PLAN_BUDGET_SECONDS)


async def test_a_retry_after_a_long_draft_asks_for_a_tighter_limit():
    first, retry = Scripted(_questions()), Scripted(_questions())
    await LLMPlanWriter(first, "m").write(_brief())
    await LLMPlanWriter(retry, "m").write(_brief(shorter=True))

    assert _stated_limit(retry.calls[0]["system"][0].text) < _stated_limit(
        first.calls[0]["system"][0].text
    )


async def test_plan_writer_failure_is_the_planners_error():
    with pytest.raises(PlanWriterError):
        await LLMPlanWriter(Scripted(LLMError("x")), "m").write(_brief())


async def test_reflect_writer_returns_a_draft_and_passes_the_words_to_avoid():
    scripted = Scripted(_ReflectOut(strength="s", next_step="n", model_example="m"))
    draft = await LLMReflectionWriter(scripted, "m").write(
        ReflectBrief("a child surprised me", "en", 2, ("wrong",), True)
    )
    assert draft == ReflectionDraft("s", "n", "m")
    assert '"avoid_these_words":["wrong"]' in scripted.calls[0]["messages"][0]["content"]


async def test_reflect_writer_failure_is_the_reflectors_error():
    with pytest.raises(ReflectWriterError):
        await LLMReflectionWriter(Scripted(LLMError("x")), "m").write(
            ReflectBrief("n", "en", 1, (), False)
        )


async def test_the_real_planner_runs_end_to_end_with_these_parts():
    planner = Planner(
        KeywordTopicResolver(), RegistryMisconceptions(), LLMPlanWriter(Scripted(_questions()), "m")
    )
    result = await planner.plan(PlanRequest("subtraction with borrowing", "en", 2, "A"))
    assert isinstance(result, Planned)
    assert result.topic_id == "NUM.G2.SUB.REGROUP"
    assert "1) Question 0?" in result.text


async def test_the_real_reflector_runs_end_to_end_with_this_writer():
    reply = _ReflectOut(
        strength="You asked how.", next_step="Ask a peer.", model_example="Who agrees?"
    )
    reflector = Reflector(LLMReflectionWriter(Scripted(reply), "m"))
    result = await reflector.reflect(ReflectRequest("Pinky 7 surprised me", "en", 2))
    assert "You asked how." in result.text
