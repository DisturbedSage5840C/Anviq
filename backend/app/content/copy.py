"""User-facing strings, loaded once from TOML files shipped inside the package."""

import tomllib
from functools import cache
from pathlib import Path

COPY_DIR = Path(__file__).parent / "copy"
LANGS = ("hi", "en")
BILINGUAL_SEPARATOR = "\n\n"


class MissingCopyError(KeyError):
    """A copy key the code asked for has no text. Always a bug, never a user error."""


@cache
def _table(lang: str) -> dict[str, str]:
    with (COPY_DIR / f"{lang}.toml").open("rb") as handle:
        return tomllib.load(handle)


def required_keys() -> frozenset[str]:
    """Keys present in every language, so a lookup never succeeds in one and fails in another."""
    return frozenset.intersection(*(frozenset(_table(lang)) for lang in LANGS))


def render(key: str, lang: str | None) -> str:
    """Text for `key` in `lang`. Unknown language (None) gets Hindi then English."""
    if lang is None:
        return BILINGUAL_SEPARATOR.join(render(key, each) for each in LANGS)
    try:
        return _table(lang)[key]
    except KeyError:
        raise MissingCopyError(f"{key!r} missing for lang {lang!r}") from None
