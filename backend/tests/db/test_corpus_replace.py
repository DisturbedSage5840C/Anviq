import pytest

from app.core.ask.chunking import Chunk
from app.db.corpus import groups_of, replace_chunks


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))


def _textbook(book: str, page: int = 1) -> Chunk:
    return Chunk(
        "NCERT", None, "", None, None, None, page, "en", "t",
        class_level=3, subject="mathematics", book_code=book, book_title="Maths Mela",
        chapter_no=1,
    )  # fmt: skip


def _nishtha(course: int) -> Chunk:
    return Chunk("NISHTHA FLN", course, "m", None, None, None, 1, "en", "t")


def test_a_textbook_chunk_is_groupd_by_its_book_code():
    assert groups_of([_textbook("cemm1"), _textbook("cemm1", 2), _textbook("chmm1")]) == (
        ("book", "cemm1"),
        ("book", "chmm1"),
    )


def test_a_course_chunk_is_groupd_by_source_and_course():
    assert groups_of([_nishtha(9), _nishtha(9), _nishtha(10)]) == (
        ("course", "NISHTHA FLN", 9),
        ("course", "NISHTHA FLN", 10),
    )


@pytest.mark.asyncio
async def test_old_rows_are_deleted_before_the_new_ones_are_inserted():
    conn = FakeConn()

    written = await replace_chunks(conn, [_textbook("cemm1")], [None])

    kinds = [sql.split()[0] for sql, _ in conn.calls]
    assert kinds == ["delete", "insert"]
    assert "book_code" in conn.calls[0][0]
    assert conn.calls[0][1] == {"book_code": "cemm1"}
    assert written == 1


@pytest.mark.asyncio
async def test_nothing_is_deleted_when_there_is_nothing_to_insert():
    conn = FakeConn()

    assert await replace_chunks(conn, [], []) == 0
    assert conn.calls == []
