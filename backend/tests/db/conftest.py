import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    """A connection whose work is always rolled back, so tests leave no rows behind."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()
