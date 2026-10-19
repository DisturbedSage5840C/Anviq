"""Does the coach agree with expert labels? Target: mean kappa >= 0.6, no criterion below 0.5.

Plan section 8, row 2. The gold set is JSON lines, one teacher turn each, labelled by two people
and adjudicated:

    {"move_id": 2, "child_text": "45", "teacher_text": "...", "labels": {"C1": true, ...}}

    python -m app.evaluation.coach_kappa --gold ../eval/datasets/gold_turns.jsonl
    python -m app.evaluation.coach_kappa --from-rubrics   # smoke set from the rubric examples
    python -m app.evaluation.coach_kappa --from-rubrics --offline   # no key: checks the harness
"""

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import get_settings
from app.core.children.personas import ChildState
from app.core.coach import Coach, CoachRequest, CoachUnavailableError, CoachVerdict
from app.core.rehearsal import Scorer
from app.core.rubric import MOVES, load_rubric
from app.evaluation.metrics import cohen_kappa
from app.llm.client import LLMClient

KAPPA_TARGET = 0.6
KAPPA_FLOOR = 0.5


@dataclass(frozen=True)
class Gold:
    move_id: int
    child_text: str
    teacher_text: str
    labels: dict[str, bool]


def load_gold(path: Path) -> list[Gold]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            rows.append(
                Gold(raw["move_id"], raw.get("child_text", ""), raw["teacher_text"], raw["labels"])
            )
    return rows


def gold_from_rubrics(moves: range = range(1, 3)) -> list[Gold]:
    """The rubric's own labelled examples: a smoke test, not a substitute for the human set."""
    out = []
    for move_id in moves:
        rubric = load_rubric(move_id)
        for example in rubric.examples:
            labels = {cid: cid in example.met for cid in rubric.criterion_ids}
            out.append(Gold(move_id, "45", example.text, labels))
    return out


class Oracle:
    """Offline stand-in that returns the gold labels, so the harness can be checked end to end."""

    def __init__(self, gold: list[Gold]) -> None:
        self._by_text = {g.teacher_text: g for g in gold}

    async def score(self, request: CoachRequest) -> CoachVerdict:
        labels = self._by_text[request.teacher_text].labels
        return CoachVerdict(request.move_id, labels, {}, "", "")


async def run(coach: Scorer, gold: list[Gold], concurrency: int) -> dict[str, object]:
    gate = asyncio.Semaphore(concurrency)

    async def one(item: Gold) -> tuple[Gold, CoachVerdict | None]:
        request = CoachRequest(
            item.move_id, "A", "hi", "Riya", item.child_text, item.teacher_text, ChildState.CONFUSED
        )
        async with gate:
            try:
                return item, await coach.score(request)
            except CoachUnavailableError:
                return item, None

    results = await asyncio.gather(*(one(g) for g in gold))
    human: dict[str, list[bool]] = defaultdict(list)
    model: dict[str, list[bool]] = defaultdict(list)
    failed = 0
    for item, verdict in results:
        if verdict is None:
            failed += 1
            continue
        for cid, label in item.labels.items():
            human[f"{item.move_id}:{cid}"].append(label)
            model[f"{item.move_id}:{cid}"].append(bool(verdict.criteria.get(cid, False)))
    kappas = {key: round(cohen_kappa(human[key], model[key]), 3) for key in sorted(human)}
    mean = sum(kappas.values()) / len(kappas) if kappas else 0.0
    return {
        "turns": len(gold),
        "unscored": failed,
        "kappa_by_criterion": kappas,
        "mean_kappa": round(mean, 3),
        "pass": bool(kappas) and mean >= KAPPA_TARGET and min(kappas.values()) >= KAPPA_FLOOR,
    }


async def _main(args: argparse.Namespace) -> None:
    gold = (
        gold_from_rubrics(MOVES if args.all_moves else range(1, 3))
        if args.from_rubrics
        else load_gold(args.gold)
    )
    if args.offline:
        report = await run(Oracle(gold), gold, args.concurrency)
    else:
        settings = get_settings()
        if settings.anthropic_api_key is None:
            raise SystemExit("ANTHROPIC_API_KEY is not set; use --offline to check the harness")
        async with httpx.AsyncClient() as http:
            client = LLMClient(http, settings.anthropic_api_key.get_secret_value())
            model = settings.model_fast if args.fast else settings.model_smart
            report = await run(Coach(client, model), gold, args.concurrency)
    report["offline"] = args.offline
    report["source"] = "rubric examples" if args.from_rubrics else str(args.gold)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("turns", "mean_kappa", "pass")}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("../eval/datasets/gold_turns.jsonl"))
    parser.add_argument("--from-rubrics", action="store_true")
    parser.add_argument("--all-moves", action="store_true", help="with --from-rubrics: moves 1-6")
    parser.add_argument("--fast", action="store_true", help="score with MODEL_FAST (cost check)")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("../eval/results/coach_kappa.json"))
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
