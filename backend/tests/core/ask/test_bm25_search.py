import asyncio
from collections.abc import Sequence

import pytest

from app.db.corpus import Bm25Search, ChunkRow, content_words

ROWS = {
    "en": [
        ChunkRow("1", "Course 6", "Course overview: the teaching approach and stages.", None),
        ChunkRow("2", "Course 9", "ELPS means experience, language, pictorial, symbolic.", None),
        ChunkRow("3", "Course 7", "Storytelling in the classroom.", "About teaching routines"),
    ],
    "hi": [ChunkRow("4", "Course 9 hi", "बंडल बनाकर दहाई समझाएँ", None)],
}


class FakeLoader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, lang: str) -> Sequence[ChunkRow]:
        self.calls.append(lang)
        return ROWS[lang]


def test_content_words_drop_filler_and_duplicates_in_question_order():
    assert content_words("How to teach ELPS and teach it?") == ("teach", "elps")


def test_content_words_keep_filler_when_nothing_else_is_left():
    assert content_words("how to do it") == ("how", "to", "do", "it")


async def test_rare_word_finds_its_passage_with_label_and_text():
    search = Bm25Search(FakeLoader())

    found = await search.search("What is ELPS?", "en", 3)

    assert [(p.chunk_id, p.label) for p in found][:1] == [("2", "Course 9")]
    assert found[0].text.startswith("ELPS means")
    assert 0.0 < found[0].score <= 1.0


async def test_context_line_is_searched_but_not_shown():
    search = Bm25Search(FakeLoader())

    found = await search.search("routines", "en", 3)

    assert found[0].chunk_id == "3"
    assert "routines" not in found[0].text


async def test_each_language_is_loaded_once_and_searched_in_its_own_corpus():
    loader = FakeLoader()
    search = Bm25Search(loader)

    await search.search("ELPS", "en", 3)
    await search.search("approach", "en", 3)
    hindi = await search.search("बंडल", "hi", 3)

    assert loader.calls == ["en", "hi"]
    assert [p.chunk_id for p in hindi] == ["4"]


def test_content_words_ignore_a_trailing_danda_so_filler_is_still_dropped():
    assert content_words("दहाई कैसे समझाएँ है।") == ("दहाई", "समझाएँ")


async def test_a_hindi_word_before_a_danda_is_found_by_its_bare_form():
    rows = {"hi": [ChunkRow("4", "Course 9 hi", "बंडल बनाकर दहाई समझाएँ। अगला चरण।", None)]}

    async def load(lang: str) -> Sequence[ChunkRow]:
        return rows[lang]

    found = await Bm25Search(load).search("समझाएँ", "hi", 3)

    assert [p.chunk_id for p in found] == ["4"]


async def test_a_failed_load_is_not_cached_and_the_next_search_retries():
    attempts: list[str] = []

    async def load(lang: str) -> Sequence[ChunkRow]:
        attempts.append(lang)
        if len(attempts) == 1:
            raise ConnectionError("db down")
        return ROWS[lang]

    search = Bm25Search(load)

    with pytest.raises(ConnectionError):
        await search.search("ELPS", "en", 3)
    found = await search.search("ELPS", "en", 3)

    assert [p.chunk_id for p in found][:1] == ["2"]
    assert attempts == ["en", "en"]


async def test_an_empty_corpus_is_not_cached_so_a_later_ingest_is_seen():
    corpus: list[ChunkRow] = []

    async def load(lang: str) -> Sequence[ChunkRow]:
        return corpus

    search = Bm25Search(load)

    assert await search.search("ELPS", "en", 3) == []
    corpus.extend(ROWS["en"])

    assert [p.chunk_id for p in await search.search("ELPS", "en", 3)][:1] == ["2"]


async def test_concurrent_first_searches_load_the_language_once():
    loader = FakeLoader()
    search = Bm25Search(loader)

    await asyncio.gather(*(search.search("ELPS", "en", 3) for _ in range(5)))

    assert loader.calls == ["en"]


async def test_a_question_with_no_words_finds_nothing_and_loads_nothing():
    loader = FakeLoader()

    assert await Bm25Search(loader).search("?!", "en", 3) == []
    assert loader.calls == []
