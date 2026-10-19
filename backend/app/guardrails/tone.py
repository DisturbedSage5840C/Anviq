"""Tone lexicon: words a coach must never say to a teacher about their own teaching.

A lexicon is blunt on purpose. It cannot judge warmth, but it reliably catches the failure that
matters most (a verdict on the teacher), cheaply and offline. The model-based tone check lives in
the eval harness, not on the request path (plan section 4.8).
"""

import re
import unicodedata

_ENGLISH = (
    "wrong",
    "bad",
    "poor",
    "lazy",
    "useless",
    "terrible",
    "failed",
    "failure",
    "stupid",
    "hopeless",
    "weak",
    "incompetent",
)
_HINDI = (
    "गलत",
    "बेकार",
    "खराब",
    "आलसी",
    "नाकाम",
    "निकम्मा",
    "कमज़ोर",
    "कमजोर",
)

# Whole words only: a lookaround on word characters and the Devanagari block, because `\b` treats
# Hindi vowel signs as breaks and would match "गलत" inside "गलती".
_WORD_CHARS = r"[\wऀ-ॿ]"
_HARSH = re.compile(
    rf"(?<!{_WORD_CHARS})(?:{'|'.join(map(re.escape, (*_ENGLISH, *_HINDI)))})(?!{_WORD_CHARS})"
)


def harsh_terms(text: str) -> tuple[str, ...]:
    """Harsh words found in `text`, each once, in order of first appearance."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return tuple(dict.fromkeys(match.group(0) for match in _HARSH.finditer(folded)))
