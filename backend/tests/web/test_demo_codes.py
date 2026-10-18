"""Demo codes: unguessable, never stored in the clear, and never reusable as an identity."""

from datetime import UTC, datetime

import pytest

from app.web.demo_codes import (
    CODE_PATTERN,
    MAX_TURNS,
    generate_code,
    hash_code,
    issue_code,
    web_identity,
)

PEPPER = b"p" * 32
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


def test_generated_codes_are_long_and_unique():
    codes = {generate_code() for _ in range(50)}

    assert len(codes) == 50
    assert all(len(code) >= 22 for code in codes)  # 128 bits of randomness, base64url


def test_the_same_code_always_hashes_the_same():
    assert hash_code(PEPPER, "abc") == hash_code(PEPPER, "abc")
    assert len(hash_code(PEPPER, "abc")) == 32


def test_a_different_code_or_pepper_gives_a_different_hash():
    assert hash_code(PEPPER, "abc") != hash_code(PEPPER, "abd")
    assert hash_code(PEPPER, "abc") != hash_code(b"q" * 32, "abc")


def test_the_web_identity_is_stable_opaque_and_marked_as_web():
    code_hash = hash_code(PEPPER, "secret-code")

    identity = web_identity(code_hash)

    assert identity == web_identity(code_hash)
    assert identity.startswith("web:")
    assert "secret-code" not in identity


def test_generated_codes_have_the_shape_the_api_checks_for():
    assert all(CODE_PATTERN.fullmatch(generate_code()) for _ in range(50))


async def test_a_code_cannot_be_issued_with_no_turns_or_a_free_for_all():
    for turns in (0, -1, MAX_TURNS + 1):
        with pytest.raises(ValueError):
            await issue_code(None, PEPPER, now=NOW, turns=turns)  # type: ignore[arg-type]
