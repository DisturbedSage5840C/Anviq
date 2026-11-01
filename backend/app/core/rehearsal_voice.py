"""What the voice note says for one rehearsal turn.

The written message is laid out for reading: "Riya: <line>", an emoji, the coach's note. Read aloud
that sounds like a label and a symbol. The voice note is composed from the turn's outcome instead:
the child's line first, then the growth level in a word, then the coach's note in plain sentences.
"""

from app.content.copy import render
from app.core.coach import NUDGE_BELOW, CoachVerdict
from app.core.mirror import growth_label
from app.core.rehearsal import TurnOutcome
from app.core.self_rating import rating_prompt
from app.speech.prepare import to_spoken


def spoken_turn(outcome: TurnOutcome, lang: str) -> str:
    """The child's line, then the coach's growth note, then the summary, as one spoken text."""
    parts = [
        to_spoken(outcome.child_text, lang) if outcome.child is not None else "",
        _coach_part(outcome, lang),
        to_spoken(outcome.summary, lang) if outcome.summary else "",
    ]
    return " ".join(part for part in parts if part)


def _coach_part(outcome: TurnOutcome, lang: str) -> str:
    if outcome.ask_rating:
        return to_spoken(rating_prompt(lang), lang)
    if outcome.verdict is not None and outcome.nudge:
        return _verdict_part(outcome.verdict, lang)
    if outcome.verdict is None and outcome.child is not None and not outcome.finished:
        return to_spoken(render("rehearsal_coach_unavailable", lang), lang)
    return ""


def _verdict_part(verdict: CoachVerdict, lang: str) -> str:
    level = render("spoken_growth", lang).format(growth=growth_label(verdict.growth, lang))
    if verdict.met_count >= NUDGE_BELOW:
        return f"{level} {render('spoken_coach_ok', lang)}"
    sentences = [level, to_spoken(verdict.feedback, lang)]
    if verdict.better_phrasing:
        phrasing = to_spoken(verdict.better_phrasing, lang)
        sentences.append(f"{render('coach_nudge_phrasing', lang)}: {phrasing}")
    return " ".join(sentence for sentence in sentences if sentence)
