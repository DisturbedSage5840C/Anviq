import hashlib
import re
from pathlib import Path

import pytest

from app.content.copy import MissingCopyError, render, required_keys
from app.core.router import CONSENT_VERSION

ROUTER_SOURCE = Path(__file__).parents[2] / "app" / "core" / "router.py"
LANGS = ("hi", "en")


def _router_keys() -> set[str]:
    """Every literal copy key the router can emit, scraped from its source."""
    source = ROUTER_SOURCE.read_text(encoding="utf-8")
    keys = set(re.findall(r'Say\("([a-z_]+)"\)', source))
    for call in re.findall(r"_say\((.*?)\)\n", source, flags=re.S):
        keys.update(re.findall(r'"([a-z_]+)"', call))
    return keys


@pytest.mark.parametrize("lang", LANGS)
def test_every_router_key_has_copy_in_each_language(lang: str):
    missing = [key for key in _router_keys() if not render(key, lang).strip()]
    assert missing == []


def test_required_keys_cover_everything_the_router_emits():
    assert _router_keys() <= required_keys()


@pytest.mark.parametrize("lang", LANGS)
def test_unknown_key_raises(lang: str):
    with pytest.raises(MissingCopyError):
        render("no_such_key", lang)


def test_hindi_copy_is_devanagari_and_english_is_not():
    assert re.search(r"[ऀ-ॿ]", render("ask_grade", "hi"))
    assert not re.search(r"[ऀ-ॿ]", render("ask_grade", "en"))


def test_welcome_is_bilingual_because_language_is_unknown_yet():
    welcome = render("welcome", None)
    assert re.search(r"[ऀ-ॿ]", welcome)
    assert re.search(r"[A-Za-z]{4,}", welcome)


def test_consent_notice_names_the_deletion_command_and_what_is_not_kept():
    for lang in LANGS:
        text = render("consent_notice", lang)
        assert "90" in text


@pytest.mark.parametrize(("lang", "command"), [("hi", "सहमति वापस"), ("en", "withdraw consent")])
def test_consent_notice_tells_teachers_how_to_withdraw(lang: str, command: str):
    assert command in render("consent_notice", lang)


def test_router_key_scrape_is_not_vacuous():
    assert {"welcome", "consent_notice", "deleted"} <= _router_keys()


# If this fails you changed what a teacher consents to. Bump CONSENT_VERSION in core/router.py,
# then update the digests below in the same commit.
CONSENT_DIGESTS = {
    "v1": {
        "hi": "6e2613b5863c8ff23b559a7999a38fe14f5bbb8efd5828798499a8613f32e391",
        "en": "3a384f70acdb63daab9dc4b5a91751e971af669dfd378dc51bd36bbf7ae2fd51",
    },
    "v2": {
        "hi": "a07e9c26f8256732c2e208e5d31a88dd3558f44417fcd66641d460c3dcaff102",
        "en": "0ed8fd6c3780d6fe3e04b825de36a1a8da7cbaec83ca2c48db76dba3b831ebee",
    },
    "v3": {
        "hi": "9e23a74a2ad8677a71b420ca18f5d1ff27a3d584ce12abda588390a32bf703d7",
        "en": "8475ab67476e31283896438450a22a5e43cfef088805c48398630eac741ace38",
    },
}


@pytest.mark.parametrize("lang", LANGS)
def test_consent_text_is_pinned_to_its_version(lang: str):
    digest = hashlib.sha256(render("consent_notice", lang).encode("utf-8")).hexdigest()
    assert CONSENT_DIGESTS[CONSENT_VERSION][lang] == digest
