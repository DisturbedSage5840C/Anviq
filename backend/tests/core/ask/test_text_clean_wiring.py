from pathlib import Path

import pytest

from app.core.ask import ingest
from app.core.ask.answer import _documents
from app.core.ask.chunking import SourceDoc
from app.core.ask.retrieve import Passage

GARBLED = "बच््चोों को पढ़ाएं"
CLEAN = "बच्चों को पढ़ाएं"


def test_text_sent_to_the_model_as_a_source_document_is_cleaned():
    passage = Passage("c1", "NISHTHA FLN, Module 2", GARBLED, 0.5)

    documents = _documents([passage])

    assert documents[0]["source"]["data"] == CLEAN


def test_pages_are_cleaned_before_they_are_chunked_and_stored(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ingest, "pdf_pages", lambda path: iter([(1, GARBLED * 20)]))
    doc = SourceDoc("NISHTHA FLN", 9, "Foundational Numeracy", "hi")

    chunks = ingest.chunks_for(Path("unused.pdf"), doc)

    assert chunks
    assert all("््" not in chunk.text and "ोों" not in chunk.text for chunk in chunks)
