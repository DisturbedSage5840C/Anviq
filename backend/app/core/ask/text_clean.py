"""Repair extraction artefacts in Devanagari text before it is stored or shown to the model.

PDF text extraction sometimes emits a vowel sign, anusvara, nukta or virama twice ('बच््चोों' for
'बच्चों'). Correct Devanagari never repeats an identical combining mark back to back, so collapsing
each run to one is safe. Joiners (ZWJ/ZWNJ) are left alone: they shape conjuncts on purpose.

Two other glyph mix-ups are mapped back too: the running header "मॉड्यूल" comes out with a stray
U+0120, and Latin ligature glyphs (fi, fl, ...) come out as single code points.
"""

import re
import unicodedata

# Candrabindu..visarga, nukta, vowel signs and virama, stress signs, and the vocalic signs.
_COMBINING_MARK = r"[ऀ-ःऺ-़ा-ॏ॑-ॗॢॣ]"
_REPEATED_MARK = re.compile(rf"({_COMBINING_MARK})\1+")
_MODULE_HEADER = "मॉ\u0120ूल"
_LIGATURES = {
    ord("\ufb00"): "ff",
    ord("\ufb01"): "fi",
    ord("\ufb02"): "fl",
    ord("\ufb03"): "ffi",
    ord("\ufb04"): "ffl",
}


def clean_text(text: str) -> str:
    """The text in composed form, with doubled combining marks collapsed and known glyphs mapped."""
    composed = unicodedata.normalize("NFC", text).translate(_LIGATURES)
    return _REPEATED_MARK.sub(r"\1", composed).replace(_MODULE_HEADER, "मॉड्यूल")
