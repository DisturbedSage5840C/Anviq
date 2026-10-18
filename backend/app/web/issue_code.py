"""Issue a web-room demo code: `uv run python -m app.web.issue_code --turns 20`.

Prints the code once; only its hash is stored, so a lost code cannot be recovered. Run it with
the same PHONE_PEPPER as the API, or the API will not recognise the code.
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.privacy.keyring import load_keyring
from app.web.demo_codes import DEFAULT_TURNS, MAX_TURNS, issue_code


async def _issue(turns: int) -> str:
    settings = get_settings()
    pepper = load_keyring(settings).phone_pepper
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            return await issue_code(conn, pepper, now=datetime.now(UTC), turns=turns)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a web-room demo code.")
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS, help="turns the code allows")
    args = parser.parse_args()
    if not 1 <= args.turns <= MAX_TURNS:
        parser.error(f"--turns must be between 1 and {MAX_TURNS}")
    print(asyncio.run(_issue(args.turns)))  # noqa: T201 - the code is this command's output


if __name__ == "__main__":
    main()
