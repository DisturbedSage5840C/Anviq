"""scripts/verify_deletion.sql: the operator's proof that "delete my data" left nothing behind."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.test_erase_coverage import _erase, _seed_teacher_with_everything

SCRIPT = (Path(__file__).parents[2] / "scripts" / "verify_deletion.sql").read_text()
MISSING_ID = "00000000-0000-0000-0000-000000000000"


async def _verify(conn: AsyncConnection, teacher_id: str | None) -> None:
    if teacher_id is not None:
        await conn.execute(
            text("select set_config('anviq.teacher_id', :t, true)"), {"t": teacher_id}
        )
    await conn.exec_driver_sql(SCRIPT)


async def test_a_teacher_who_still_has_rows_fails_the_check_and_names_the_table(
    conn: AsyncConnection,
):
    teacher_id = await _seed_teacher_with_everything(conn)

    with pytest.raises(DBAPIError, match="table teachers still holds 1 row"):
        await _verify(conn, teacher_id)


async def test_an_erased_teacher_passes_the_check(conn: AsyncConnection):
    teacher_id = await _seed_teacher_with_everything(conn)
    await _erase(conn)

    await _verify(conn, teacher_id)


async def test_a_teacher_that_never_existed_passes_too(conn: AsyncConnection):
    await _verify(conn, MISSING_ID)


async def test_running_without_a_teacher_id_is_an_error_not_a_pass(conn: AsyncConnection):
    with pytest.raises(DBAPIError, match="anviq.teacher_id"):
        await _verify(conn, None)
