"""Plain text for the teacher: no emoji, no pictographs and no markdown markers.

Teachers read Anviq on WhatsApp, on older phones and through screen readers, and the same words
are sent to a voice. Prompts ask the model for plain text, and `plain_text` is the check that
makes it true when the model forgets. Line breaks and "- " lists are kept; everything that only
decorates (emoji, arrows, bold, headings, code ticks) is dropped. The patterns here are shared
with `app.speech.prepare`, so what is cleaned for the eye and for the ear cannot drift apart.
"""

import re

SYMBOLS = re.compile(
    "[\U0001f000-\U0001faff"  # pictographs and emoji
    "←-⇿"  # arrows
    "☀-➿"  # symbols and dingbats
    "⤀-⥿"  # supplemental arrows
    "⬀-⯿"  # stars, large arrows
    "\ufe0f\u200d]"  # emoji variation selector and joiner
)
HEADING_MARKER = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*")
BOLD = re.compile(r"(\*\*|__)(.+?)\1")
ITALIC_STAR = re.compile(r"\*(\S(?:[^*]*?\S)?)\*")
ITALIC_UNDERSCORE = re.compile(r"(?<!\w)_(\S(?:[^_]*?\S)?)_(?!\w)")
LEFTOVER_MARKUP = re.compile(r"[*#~`]+")

_STAR_BULLET = re.compile(r"^([ \t]*)[*•][ \t]+")
_INVISIBLE_JOINERS = re.compile("[\ufe0f\u200d]")
_SPACES = re.compile(r"[ \t]+")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"[ \t]+([.,;:!?।])")


def plain_text(text: str) -> str:
    """`text` without emoji or markdown markers, keeping line breaks and "- " lists."""
    without_joiners = _INVISIBLE_JOINERS.sub("", text)
    lines = (_plain_line(line) for line in without_joiners.splitlines())
    return "\n".join(lines).strip()


def _plain_line(line: str) -> str:
    bulleted = _STAR_BULLET.sub(r"\1- ", line)
    unheaded = HEADING_MARKER.sub("", bulleted)
    unbolded = BOLD.sub(r"\2", unheaded)
    unslanted = ITALIC_UNDERSCORE.sub(r"\1", ITALIC_STAR.sub(r"\1", unbolded))
    unmarked = LEFTOVER_MARKUP.sub("", SYMBOLS.sub(" ", unslanted))
    spaced = _SPACES.sub(" ", unmarked)
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", spaced).strip()
