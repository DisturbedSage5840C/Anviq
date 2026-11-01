from app.core.ask.chunking import Chunk, SourceDoc, chunk_document


def _textbook(**overrides: object) -> SourceDoc:
    fields: dict[str, object] = {
        "source": "NCERT",
        "course_no": None,
        "course_title": "",
        "lang": "en",
        "class_level": 3,
        "subject": "mathematics",
        "book_code": "cemm1",
        "book_title": "Maths Mela",
        "chapter_no": 4,
    }
    return SourceDoc(**{**fields, **overrides})  # type: ignore[arg-type]


def _chunk(**overrides: object) -> Chunk:
    fields: dict[str, object] = {
        "source": "NCERT",
        "course_no": None,
        "course_title": "",
        "module": None,
        "section_no": None,
        "section_title": None,
        "page": 12,
        "lang": "en",
        "text": "t",
        "class_level": 3,
        "subject": "mathematics",
        "book_code": "cemm1",
        "book_title": "Maths Mela",
        "chapter_no": 4,
    }
    return Chunk(**{**fields, **overrides})  # type: ignore[arg-type]


def test_textbook_label_names_class_book_chapter_and_page():
    assert _chunk().label() == "NCERT Class 3 Maths Mela, Ch 4, p.12"


def test_textbook_label_includes_the_chapter_title_when_known():
    label = _chunk(chapter_title="Fun with Shapes").label()

    assert label == "NCERT Class 3 Maths Mela, Ch 4: Fun with Shapes, p.12"


def test_textbook_label_leaves_out_what_is_not_known():
    assert _chunk(chapter_no=None).label() == "NCERT Class 3 Maths Mela, p.12"
    assert _chunk(book_title=None).label() == "NCERT Class 3, Ch 4, p.12"


def test_pedagogy_labels_are_unchanged():
    nishtha = Chunk("NISHTHA FLN", 9, "Foundational Numeracy", "3", "3.2", "t", 1, "en", "x")
    nipun = Chunk("NIPUN Bharat", None, "", None, "5.2", None, 1, "en", "x")

    assert nishtha.label() == "NISHTHA FLN Course 9: Foundational Numeracy, Module 3, §3.2"
    assert nipun.label() == "NIPUN Bharat, §5.2"


def test_chunks_carry_the_textbook_metadata_of_their_document():
    pages = [(2, "Count the beads. " * 40)]

    chunks = chunk_document(_textbook(chapter_title="Beads"), pages)

    assert chunks
    assert {c.book_code for c in chunks} == {"cemm1"}
    assert {(c.class_level, c.subject, c.chapter_no, c.chapter_title) for c in chunks} == {
        (3, "mathematics", 4, "Beads")
    }
    assert chunks[0].page == 2


def test_numbers_in_textbook_text_are_not_mistaken_for_headings():
    body = "3.5 kg of rice costs more than 2.5 kg of rice. " * 30
    pages = [(1, f"{body}\n3.2 Weigh the apples\n{body}")]

    textbook = chunk_document(_textbook(), pages)
    guidance = chunk_document(SourceDoc("NIPUN Bharat", None, "", "en"), pages)

    assert all(c.section_no is None for c in textbook)
    assert any(c.section_no == "3.2" for c in guidance)


def test_each_chunk_reports_the_page_where_its_text_starts():
    pages = [(page, f"page{page} " * 250) for page in (5, 6, 7)]

    chunks = chunk_document(_textbook(), pages)

    assert [c.page for c in chunks] == [5, 6, 7]
    assert all(c.text.startswith(f"page{c.page}") for c in chunks)


def test_a_chunk_that_spans_two_pages_reports_the_first_of_them():
    pages = [(8, "alpha " * 100), (9, "beta " * 100)]

    chunks = chunk_document(_textbook(), pages)

    assert len(chunks) == 1
    assert chunks[0].page == 8
