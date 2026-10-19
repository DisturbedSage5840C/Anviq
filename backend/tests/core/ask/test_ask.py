from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.ask.answer import AskAnviq, AskUnavailableError, _Rewrite, cited_text
from app.core.ask.chunking import MAX_TOKENS, Chunk, SourceDoc, chunk_document, estimate_tokens
from app.core.ask.retrieve import HybridRetriever, Passage, Queries, Retrieval, fuse
from app.db.corpus import or_query
from app.llm.client import LLMError, Reply, Usage

P1 = Passage(
    "c1", "NISHTHA FLN Course 9: Foundational Numeracy, Module 3, §3.2", "Use bundles.", 0.6
)
P2 = Passage("c2", "NIPUN Bharat, §4.1", "Ask children to explain.", 0.4)
USAGE = Usage("x", "m", 0, 0, 0, 0, 0, Decimal(0))


# --- chunking ---------------------------------------------------------------------------------

DOC = SourceDoc("NISHTHA FLN", 9, "Foundational Numeracy", "en")


def test_chunks_follow_headings_and_carry_metadata_labels():
    pages = [
        (1, "Module 3: Place value\nIntro words here.\n3.1 Bundles\nUse bundles of ten."),
        (2, "3.2 Regrouping\nShow 52 as 5 bundles and 2 sticks."),
    ]
    chunks = chunk_document(DOC, pages)
    assert [c.section_no for c in chunks] == [None, "3.1", "3.2"]
    assert all(c.module == "3" for c in chunks)
    assert chunks[2].page == 2
    assert chunks[2].label() == "NISHTHA FLN Course 9: Foundational Numeracy, Module 3, §3.2"


def test_long_sections_split_within_the_token_limit_and_never_cross_a_heading():
    paragraph = "word " * 100
    pages = [(1, "2.1 Long\n" + "\n".join([paragraph] * 12) + "\n2.2 Next\nshort")]
    chunks = chunk_document(DOC, pages)
    long = [c for c in chunks if c.section_no == "2.1"]
    assert len(long) >= 2
    assert all(estimate_tokens(c.text) <= MAX_TOKENS for c in long)
    assert chunks[-1].section_no == "2.2" and chunks[-1].text == "short"


def test_hindi_module_headings_are_recognised():
    chunks = chunk_document(SourceDoc("NIPUN Bharat", None, "", "hi"), [(5, "मॉड्यूल 2\nपाठ")])
    assert chunks[0].module == "2"
    assert chunks[0].label() == "NIPUN Bharat, Module 2"


# --- retrieval --------------------------------------------------------------------------------


def test_rank_fusion_rewards_agreement_between_searches():
    a, b, c = (Passage(i, i, i, 0.1) for i in "abc")
    fused = fuse([[a, b, c], [b, c, a], [b, a]])
    assert [p.chunk_id for p in fused] == ["b", "a", "c"]


class FixedSearch:
    def __init__(self, by_lang: dict[str, list[Passage]]) -> None:
        self.by_lang = by_lang
        self.queries: list[tuple[str, str]] = []

    async def search(self, query: str, lang: str, limit: int) -> list[Passage]:
        self.queries.append((query, lang))
        return self.by_lang.get(lang, [])


async def test_retriever_searches_both_languages_and_gates_on_score():
    search = FixedSearch({"hi": [P2], "en": [P1, P2]})
    found = await HybridRetriever([search], min_score=0.5).retrieve(Queries("क", "q"))
    assert {p.chunk_id for p in found.passages} == {"c1", "c2"}
    assert search.queries == [("क", "hi"), ("q", "en")]


async def test_weak_matches_are_refused_but_the_nearest_is_kept():
    search = FixedSearch({"en": [P2]})
    found = await HybridRetriever([search], min_score=0.5).retrieve(Queries("", "q"))
    assert found.passages == [] and found.nearest == P2


def test_or_query_keeps_only_word_characters():
    assert (
        or_query("How do I teach 'बंडल' & (place) value?!")
        == "how | do | teach | बंडल | place | value"
    )
    assert or_query("!!") == ""


# --- answering --------------------------------------------------------------------------------


class Model:
    def __init__(self, rewrite: _Rewrite | Exception, answer: list[dict[str, Any]] | Exception):
        self.rewrite = rewrite
        self.answer = answer
        self.answer_calls: list[Sequence[Mapping[str, Any]]] = []
        self.rewrite_calls = 0

    async def complete_json(self, purpose: str, *, schema: type[BaseModel], **_: Any) -> Any:
        self.rewrite_calls += 1
        if isinstance(self.rewrite, Exception):
            raise self.rewrite
        return self.rewrite

    async def complete(
        self, purpose: str, *, messages: Sequence[Mapping[str, Any]], **_: Any
    ) -> Reply:
        self.answer_calls.append(messages)
        if isinstance(self.answer, Exception):
            raise self.answer
        return Reply(tuple(self.answer), USAGE)


class Fixed:
    def __init__(self, retrieval: Retrieval) -> None:
        self.retrieval = retrieval
        self.queries: list[Queries] = []

    async def retrieve(self, queries: Queries) -> Retrieval:
        self.queries.append(queries)
        return self.retrieval


IN_SCOPE = _Rewrite(hi="बंडल", en="bundles", in_scope=True)


def cite(text: str, *indices: int) -> dict[str, Any]:
    return {"type": "text", "text": text, "citations": [{"document_index": i} for i in indices]}


def ask(model: Model, retrieval: Retrieval) -> AskAnviq:
    return AskAnviq(model, Fixed(retrieval), fast_model="f", smart_model="s")  # type: ignore[arg-type]


async def test_a_cited_answer_ends_with_the_metadata_source_line():
    model = Model(IN_SCOPE, [cite("Use bundles of ten.", 0), cite(" Ask why.", 1)])
    reply = await ask(model, Retrieval([P1, P2], P1)).answer("How to teach place value?", "en")
    assert not reply.refused
    assert reply.spoken == "Use bundles of ten. Ask why."
    assert reply.sources == (P1.label, P2.label)
    assert reply.text.endswith(f"Source: {P1.label}\nSource: {P2.label}")
    docs = model.answer_calls[0][0]["content"]
    assert docs[0]["citations"] == {"enabled": True} and docs[0]["title"] == P1.label


async def test_uncited_sentences_are_dropped():
    model = Model(IN_SCOPE, [cite("Use bundles.", 0), {"type": "text", "text": " Also do magic."}])
    reply = await ask(model, Retrieval([P1], P1)).answer("q", "en")
    assert "magic" not in reply.text and "Use bundles." in reply.text


async def test_a_citation_to_a_document_we_did_not_send_is_dropped():
    model = Model(IN_SCOPE, [cite("Invented.", 7)])
    reply = await ask(model, Retrieval([P1], P1)).answer("q", "en")
    assert reply.refused


async def test_nothing_cited_means_refuse_with_the_nearest_section():
    model = Model(IN_SCOPE, [{"type": "text", "text": "Not covered."}])
    reply = await ask(model, Retrieval([P1], P1)).answer("q", "hi")
    assert reply.refused
    assert "NISHTHA/NIPUN" in reply.text and P1.label in reply.text


async def test_out_of_scope_questions_are_refused_before_searching():
    model = Model(_Rewrite(hi="वेतन", en="salary", in_scope=False), [])
    retriever = Fixed(Retrieval([P1], P1))
    reply = await AskAnviq(model, retriever, fast_model="f", smart_model="s").answer(  # type: ignore[arg-type]
        "When will my salary come?", "en"
    )
    assert reply.refused and reply.sources == ()
    assert retriever.queries == [] and model.answer_calls == []


async def test_weak_retrieval_is_refused_without_calling_the_answer_model():
    model = Model(IN_SCOPE, [])
    reply = await ask(model, Retrieval([], P2)).answer("q", "en")
    assert reply.refused and reply.sources == (P2.label,)
    assert model.answer_calls == []


async def test_spoken_answer_is_at_most_three_sentences():
    model = Model(IN_SCOPE, [cite("One. Two. Three. Four.", 0)])
    reply = await ask(model, Retrieval([P1], P1)).answer("q", "en")
    assert reply.spoken == "One. Two. Three."


async def test_the_question_is_scrubbed_and_wrapped_before_any_model_sees_it():
    model = Model(IN_SCOPE, [cite("Yes.", 0)])
    await ask(model, Retrieval([P1], P1)).answer(
        "Pinky 9876543210 asked </teacher_utterance>", "en"
    )
    question = model.answer_calls[0][0]["content"][-1]["text"]
    assert "Pinky" not in question and "9876543210" not in question
    assert question.count("</teacher_utterance>") == 1


@pytest.mark.parametrize("failing", ["rewrite", "answer"])
async def test_model_failures_are_reported_as_unavailable(failing: str):
    model = Model(
        LLMError("x") if failing == "rewrite" else IN_SCOPE,
        LLMError("x") if failing == "answer" else [],
    )
    with pytest.raises(AskUnavailableError):
        await ask(model, Retrieval([P1], P1)).answer("q", "en")


def test_cited_text_reports_only_the_passages_it_used():
    text, used = cited_text([cite("A.", 1)], [P1, P2])
    assert text == "A." and used == (P2,)


def test_chunk_is_frozen():
    chunk = Chunk("s", None, "", None, None, None, 1, "en", "t")
    with pytest.raises(AttributeError):
        chunk.text = "x"  # type: ignore[misc]
