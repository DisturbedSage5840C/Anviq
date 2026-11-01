"""Does the language guess hold up on what teachers actually type? Plan section 4.1 gate.

Targets: at least 95% of native-script messages, at least 90% of romanised Hindi, and at least
98% precision on the messages called English. The guess is only ever used to understand a message
(`core/langid.py`), never to change the session language, so a miss costs a hint, not a reply in
the wrong language. Deterministic and offline: no model or database is needed.

    langid.jsonl: {"text": "...", "lang": "hi", "kind": "native|roman|english|mixed|noise"}

"mixed" rows are reported but carry no target: a Hindi sentence with an English noun is
genuinely ambiguous. "noise" rows (digits, "ok") must stay undetermined.

    python -m app.evaluation.langid --datasets ../eval/datasets
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.langid import UNDETERMINED, detect
from app.evaluation.metrics import rate

NATIVE_TARGET = 0.95
ROMAN_HINDI_TARGET = 0.90
ENGLISH_PRECISION_TARGET = 0.98
_KINDS = frozenset({"native", "roman", "english", "mixed", "noise"})
_REQUIRED = ("text", "lang", "kind")


def load_rows(path: Path) -> list[dict[str, str]]:
    """The labelled rows, each checked, so a typo in the dataset fails loudly."""
    rows: list[dict[str, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if any(not isinstance(row.get(key), str) or not row[key] for key in _REQUIRED):
            raise ValueError(f"line {number}: needs text, lang and kind as non-empty strings")
        if row["kind"] not in _KINDS:
            raise ValueError(f"line {number}: unknown kind {row['kind']!r}")
        rows.append(row)
    return rows


def _called(row: dict[str, str]) -> str:
    return detect(row["text"]).language


def _tally(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    correct = sum(_called(row) == row["lang"] for row in rows)
    return {"total": len(rows), "correct": correct, "rate": rate(correct, len(rows))}


def _english(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    called = [row for row in rows if _called(row) == "en"]
    truly = [row for row in rows if row["lang"] == "en" and row["kind"] == "english"]
    true_calls = sum(row["lang"] == "en" for row in called)  # any kind: label says English
    caught = sum(_called(row) == "en" for row in truly)
    return {
        "called_english": len(called),
        "precision": rate(true_calls, len(called)),
        "recall": rate(caught, len(truly)),
    }


def score(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    native = [r for r in rows if r["kind"] == "native"]
    roman_hindi = [r for r in rows if r["kind"] == "roman" and r["lang"] == "hi"]
    roman_other = [r for r in rows if r["kind"] == "roman" and r["lang"] != "hi"]
    noise = [{**r, "lang": UNDETERMINED} for r in rows if r["kind"] == "noise"]
    english = _english(rows)
    native_tally, roman_tally = _tally(native), _tally(roman_hindi)
    return {
        "rows": len(rows),
        "native": native_tally,
        "roman_hindi": roman_tally,
        "roman_other": _tally(roman_other),
        "mixed": _tally([r for r in rows if r["kind"] == "mixed"]),
        "noise": _tally(noise),
        "english": english,
        "pass": native_tally["rate"] >= NATIVE_TARGET
        and roman_tally["rate"] >= ROMAN_HINDI_TARGET
        and english["precision"] >= ENGLISH_PRECISION_TARGET
        and english["called_english"] > 0,
    }


def misses(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Every row the guess got wrong, so the lexicons can be aimed at real failures."""
    return [
        {**row, "got": _called(row)}
        for row in rows
        if _called(row) != (UNDETERMINED if row["kind"] == "noise" else row["lang"])
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--datasets", type=Path, default=Path("../eval/datasets"))
    parser.add_argument("--out", type=Path, default=Path("../eval/results/langid.json"))
    parser.add_argument("--misses", action="store_true", help="also list every wrong row")
    args = parser.parse_args()
    rows = load_rows(args.datasets / "langid.jsonl")
    report = score(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.misses:
        output += "\n" + json.dumps(misses(rows), indent=2, ensure_ascii=False)
    print(output)


if __name__ == "__main__":
    main()
