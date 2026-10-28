"""Checks run on model output before a teacher hears it (plan section 4.10).

Each check is a plain function from text to a verdict, so it tests offline and the same checks
run in the eval harness. The lexicon for harsh words is `guardrails.tone`; this module does not
carry a second copy.
"""

import re
import unicodedata
from collections.abc import Collection

from app.core.speech_budget import truncate_to_budget
from app.guardrails.tone import harsh_terms

MAX_CHILD_SENTENCES = 2
MAX_CHILD_CHARS = 280
CITATION_PLACEHOLDER = ""

# Python's \d matches Devanagari digits, and int() reads them, so ४५ and 45 are the same number.
_NUMBER = re.compile(r"\d+")
_SENTENCE_END = re.compile(r"[।.?!]+")
# "..." is a spoken pause inside a sentence ("मुझे लगता है... 23 बड़ा है"), not the end of one.
_PAUSE = re.compile(r"\.{2,}|…")
# A lone hesitation sound ("umm...", "उम्म...") is not a sentence; a shy child may open with one.
_FILLER_WORD = re.compile(r"(?:u+m+|u+h+|h+m+|e+r+|उ+म्*म*|हम्*म*|अ+)", re.IGNORECASE)
_FILLER_EDGE_PUNCTUATION = ",;:-–—…'\"“”‘’()"
MAX_FILLER_WORD_CHARS = 12
# A child never says it is a program. English words, Devanagari spellings and brand names.
_AI_REVEAL = re.compile(
    r"(?<![\w])(?:ai|a\.i\.|artificial|language model|chatbot|bot|assistant|claude|anthropic|"
    r"openai|gpt|robot)(?![\w])|कृत्रिम|एआई|चैटबॉट|भाषा मॉडल|रोबोट|क्लॉड",
    re.IGNORECASE,
)
_TEACHER_TAG = re.compile(r"</?\s*teacher_utterance\s*>", re.IGNORECASE)


def numbers_in(text: str) -> frozenset[int]:
    return frozenset(int(token) for token in _NUMBER.findall(unicodedata.normalize("NFKC", text)))


def says_answer(utterance: str, answer: str) -> bool:
    """True when the child's words contain exactly the number `answer` (any digit script)."""
    return int(answer) in numbers_in(utterance)


def leaks_correct_answer(utterance: str, correct: str, allowed: Collection[int] = ()) -> bool:
    """True when the child states the right answer it is not meant to know yet.

    A number that is part of the problem or the child's own steps may legitimately be spoken, so
    those are passed in `allowed` and never count as a leak.
    """
    value = int(correct)
    return value not in allowed and value in numbers_in(utterance)


def reveals_ai(text: str) -> bool:
    return _AI_REVEAL.search(unicodedata.normalize("NFKC", text)) is not None


def _is_filler_only(part: str) -> bool:
    """True when every word of the fragment is a hesitation sound (and there is at least one)."""
    words = [word for word in (w.strip(_FILLER_EDGE_PUNCTUATION) for w in part.split()) if word]
    return bool(words) and all(
        len(word) <= MAX_FILLER_WORD_CHARS and _FILLER_WORD.fullmatch(word) for word in words
    )


def sentence_count(text: str) -> int:
    parts = (part for part in _SENTENCE_END.split(_PAUSE.sub(" ", text)) if part.strip())
    return sum(1 for part in parts if not _is_filler_only(part))


def child_utterance_ok(
    utterance: str, *, answer: str, correct: str, allowed: Collection[int], knows_correct: bool
) -> bool:
    """The whole in-character test for one child reply.

    It must say the computed answer, stay within two short sentences, never admit to being a
    program, and (unless the child has self-corrected) never state the right answer.
    """
    if not utterance.strip() or len(utterance) > MAX_CHILD_CHARS:
        return False
    if sentence_count(utterance) > MAX_CHILD_SENTENCES or reveals_ai(utterance):
        return False
    if not says_answer(utterance, answer):
        return False
    return knows_correct or not leaks_correct_answer(utterance, correct, allowed)


def coach_tone_ok(text: str) -> bool:
    return not harsh_terms(text)


def valid_citations(cited_ids: Collection[str], retrieved_ids: Collection[str]) -> bool:
    """Every cited chunk must be one we actually retrieved, and there must be at least one."""
    return bool(cited_ids) and set(cited_ids) <= set(retrieved_ids)


def fit_spoken(text: str, budget_seconds: float) -> str:
    return truncate_to_budget(text, budget_seconds)


def wrap_teacher_text(text: str) -> str:
    """Teacher words go to a model as data inside tags, with any fake tag in them removed."""
    return f"<teacher_utterance>{_TEACHER_TAG.sub('', text)}</teacher_utterance>"
