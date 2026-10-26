"""Repair extraction artefacts in Devanagari text before it is stored or shown to the model.

PDF text extraction sometimes emits a vowel sign, anusvara, nukta or virama twice ('बच््चोों' for
'बच्चों'). Correct Devanagari never repeats an identical combining mark back to back, so collapsing
each run to one is safe. Joiners (ZWJ/ZWNJ) are left alone: they shape conjuncts on purpose.
"""

import re
import unicodedata

# Candrabindu..visarga, nukta, vowel signs and virama, stress signs, and the vocalic signs.
_COMBINING_MARK = r"[ऀ-ःऺ-़ा-ॏ॑-ॗॢॣ]"
_REPEATED_MARK = re.compile(rf"({_COMBINING_MARK})\1+")


def clean_text(text: str) -> str:
    """The text in composed form with doubled Devanagari combining marks collapsed."""
    return _REPEATED_MARK.sub(r"\1", unicodedata.normalize("NFC", text))
