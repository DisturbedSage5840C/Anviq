"""Agreement between the second labeller and the gold labels (plan section 8, coach kappa).

The 150-turn gold set was labelled by one person. A second person fills in
eval/review/kappa_second_labeller.csv without seeing those labels; this compares the two.

    python -m app.evaluation.kappa_compare --sheet ../eval/review/kappa_second_labeller_filled.csv

Same bar as the coach: mean kappa >= 0.6 and no criterion below 0.5. Nothing is written to the
sheet or the gold set, and a sheet with a blank or invalid cell is refused, never half-scored.
"""

import argparse
import csv
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.evaluation.coach_kappa import KAPPA_FLOOR, KAPPA_TARGET, Gold, load_gold
from app.evaluation.metrics import cohen_kappa

CRITERIA = ("C1", "C2", "C3", "C4")
YES, NO = "1", "0"


class SheetError(ValueError):
    """The filled sheet, the key or the gold set cannot be compared; the message says why."""


def _parse_cell(raw: str | None, item: int, criterion: str) -> bool:
    value = (raw or "").strip()
    if value not in (YES, NO):
        shown = value or "blank"
        raise SheetError(f"item {item}, {criterion}: expected 1 or 0, found {shown}")
    return value == YES


def load_second_labels(path: Path) -> dict[int, tuple[bool, bool, bool, bool]]:
    """Item number to the four C1..C4 answers, refusing blanks and anything but 1 or 0."""
    labels: dict[int, tuple[bool, bool, bool, bool]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            item = int(row["item"])
            if item in labels:
                raise SheetError(f"item {item} appears twice in the sheet")
            a, b, c, d = (_parse_cell(row.get(cid), item, cid) for cid in CRITERIA)
            labels[item] = (a, b, c, d)
    return labels


def load_key(path: Path) -> dict[int, int]:
    """Item number to the 1-based line of the gold file that item came from."""
    with path.open(encoding="utf-8", newline="") as handle:
        return {int(row["item"]): int(row["gold_turns_line"]) for row in csv.DictReader(handle)}


def _pair(
    item: int, gold: Sequence[Gold], line: int, second: Mapping[int, Sequence[bool]]
) -> tuple[Gold, Sequence[bool]]:
    if not 1 <= line <= len(gold):
        raise SheetError(f"item {item} points at gold line {line}, outside the gold set")
    if item not in second:
        raise SheetError(f"item {item} is missing from the sheet")
    return gold[line - 1], second[item]


def compare(
    gold: Sequence[Gold],
    key: Mapping[int, int],
    second: Mapping[int, Sequence[bool]],
) -> dict[str, Any]:
    """Cohen's kappa per move and criterion, their mean, and every cell the two disagree on."""
    first_by_criterion: dict[str, list[bool]] = defaultdict(list)
    second_by_criterion: dict[str, list[bool]] = defaultdict(list)
    disagreements = []
    for item in sorted(key):
        turn, answers = _pair(item, gold, key[item], second)
        for cid, theirs in zip(CRITERIA, answers, strict=True):
            name = f"{turn.move_id}:{cid}"
            first_by_criterion[name].append(turn.labels[cid])
            second_by_criterion[name].append(theirs)
            if turn.labels[cid] != theirs:
                disagreements.append(
                    {"item": item, "criterion": cid, "gold": turn.labels[cid], "second": theirs}
                )
    kappas = {
        name: round(cohen_kappa(first_by_criterion[name], second_by_criterion[name]), 3)
        for name in sorted(first_by_criterion)
    }
    mean = round(sum(kappas.values()) / len(kappas), 3)
    cells = len(key) * len(CRITERIA)
    return {
        "turns": len(key),
        "mean_kappa": mean,
        "min_kappa": min(kappas.values()),
        "kappa_by_criterion": kappas,
        "agreement_rate": round(1 - len(disagreements) / cells, 3),
        "disagreements": disagreements,
        "pass": mean >= KAPPA_TARGET and min(kappas.values()) >= KAPPA_FLOOR,
    }


def render_markdown(result: Mapping[str, Any]) -> str:
    verdict = "PASS" if result["pass"] else "below target"
    lines = [
        "# Second labeller vs gold labels",
        "",
        f"{result['turns']} turns. Mean kappa {result['mean_kappa']:.2f} "
        f"(target >= {KAPPA_TARGET}, none below {KAPPA_FLOOR}): **{verdict}**. "
        f"Raw agreement {result['agreement_rate'] * 100:.1f}%.",
        "",
        "| Move:criterion | kappa |",
        "|---|---|",
    ]
    lines += [f"| {name} | {value:.2f} |" for name, value in result["kappa_by_criterion"].items()]
    if result["disagreements"]:
        lines += [
            "",
            "## Cells where the two labellers differ",
            "",
            "| Item | Criterion | Gold | Second |",
        ]
        lines += ["|---|---|---|---|"]
        lines += [
            f"| {d['item']} | {d['criterion']} | {int(d['gold'])} | {int(d['second'])} |"
            for d in result["disagreements"]
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sheet", type=Path, required=True, help="the filled-in CSV")
    parser.add_argument(
        "--key", type=Path, default=Path("../eval/review/kappa_second_labeller_key.csv")
    )
    parser.add_argument("--gold", type=Path, default=Path("../eval/datasets/gold_turns.jsonl"))
    parser.add_argument(
        "--out", type=Path, default=Path("../eval/results/kappa_second_labeller.json")
    )
    parser.add_argument(
        "--md", type=Path, default=Path("../eval/review/kappa_second_labeller_result.md")
    )
    args = parser.parse_args()
    try:
        result = compare(load_gold(args.gold), load_key(args.key), load_second_labels(args.sheet))
    except SheetError as error:
        raise SystemExit(f"cannot compare: {error}") from error
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.md.write_text(render_markdown(result), encoding="utf-8")
    print(f"mean kappa {result['mean_kappa']}, min {result['min_kappa']}, pass {result['pass']}")


if __name__ == "__main__":
    main()
