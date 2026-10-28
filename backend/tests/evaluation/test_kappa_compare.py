from pathlib import Path

import pytest

from app.evaluation.coach_kappa import Gold
from app.evaluation.kappa_compare import (
    SheetError,
    compare,
    load_key,
    load_second_labels,
    render_markdown,
)

HEADER = "item,move,teacher_said,child_said,C1,C2,C3,C4\n"


def _sheet(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "second.csv"
    path.write_text(HEADER + "".join(f"{row}\n" for row in rows), encoding="utf-8")
    return path


def _key(tmp_path: Path, lines: list[int]) -> Path:
    path = tmp_path / "key.csv"
    body = "".join(f"{item},{line}\n" for item, line in enumerate(lines, start=1))
    path.write_text("item,gold_turns_line\n" + body, encoding="utf-8")
    return path


def _gold(*label_rows: tuple[bool, bool, bool, bool]) -> list[Gold]:
    return [
        Gold(1, "5", "t", dict(zip(("C1", "C2", "C3", "C4"), row, strict=True)))
        for row in label_rows
    ]


def test_a_filled_sheet_is_read_as_booleans_per_item(tmp_path: Path):
    path = _sheet(tmp_path, ['1,2,"a, b",75,1,0,1,0', "2,1,x,5,0,0,0,1"])

    labels = load_second_labels(path)

    assert labels == {1: (True, False, True, False), 2: (False, False, False, True)}


def test_a_blank_cell_is_reported_with_its_item_and_column(tmp_path: Path):
    path = _sheet(tmp_path, ["1,2,x,75,1,,1,0"])

    with pytest.raises(SheetError, match=r"item 1.*C2"):
        load_second_labels(path)


def test_a_value_other_than_zero_or_one_is_rejected(tmp_path: Path):
    path = _sheet(tmp_path, ["1,2,x,75,1,yes,1,0"])

    with pytest.raises(SheetError, match="C2"):
        load_second_labels(path)


def test_a_repeated_item_number_is_rejected(tmp_path: Path):
    path = _sheet(tmp_path, ["1,2,x,75,1,0,1,0", "1,2,y,75,1,0,1,0"])

    with pytest.raises(SheetError, match="twice"):
        load_second_labels(path)


def test_the_key_maps_each_item_to_its_gold_line(tmp_path: Path):
    assert load_key(_key(tmp_path, [112, 137])) == {1: 112, 2: 137}


def test_identical_labels_give_kappa_one_on_every_criterion():
    gold = _gold((True, False, True, False), (False, True, False, True))
    second = {1: (True, False, True, False), 2: (False, True, False, True)}

    result = compare(gold, {1: 1, 2: 2}, second)

    assert result["mean_kappa"] == 1.0
    assert result["pass"] is True
    assert result["disagreements"] == []


def test_a_second_labeller_who_flips_one_criterion_fails_the_floor():
    gold = _gold(*[(i % 2 == 0, True, True, True) for i in range(10)])
    second = {i + 1: (i % 2 == 1, True, True, True) for i in range(10)}

    result = compare(gold, {i + 1: i + 1 for i in range(10)}, second)

    assert result["kappa_by_criterion"]["1:C1"] == -1.0
    assert result["pass"] is False


def test_disagreements_name_the_item_and_criterion():
    gold = _gold((True, True, True, True), (False, False, False, False))
    second = {1: (True, False, True, True), 2: (False, False, False, False)}

    result = compare(gold, {1: 1, 2: 2}, second)

    assert result["disagreements"] == [
        {"item": 1, "criterion": "C2", "gold": True, "second": False}
    ]


def test_an_item_the_key_points_outside_the_gold_set_is_rejected():
    with pytest.raises(SheetError, match="item 1"):
        compare(_gold((True, True, True, True)), {1: 9}, {1: (True, True, True, True)})


def test_an_item_missing_from_the_sheet_is_rejected():
    with pytest.raises(SheetError, match="missing"):
        compare(_gold((True, True, True, True)), {1: 1}, {})


def test_the_markdown_states_the_verdict_and_the_sample_size():
    gold = _gold((True, False, True, False), (False, True, False, True))
    result = compare(
        gold, {1: 1, 2: 2}, {1: (True, False, True, False), 2: (False, True, False, True)}
    )

    text = render_markdown(result)

    assert "2 turns" in text
    assert "1.00" in text
