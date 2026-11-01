import json
from pathlib import Path

import pytest

from app.evaluation.langid import (
    ENGLISH_PRECISION_TARGET,
    NATIVE_TARGET,
    ROMAN_HINDI_TARGET,
    load_rows,
    score,
)


def row(text: str, lang: str, kind: str) -> dict[str, str]:
    return {"text": text, "lang": lang, "kind": kind}


def test_native_accuracy_counts_only_native_rows():
    rows = [
        row("बच्चे घटाना क्यों नहीं सीख पाते", "hi", "native"),
        row("মোর ক্লাসে ত্রিশজন", "ta", "native"),  # Bengali script, labelled wrongly on purpose
        row("haan theek hai", "hi", "roman"),
    ]

    report = score(rows)

    assert report["native"] == {"total": 2, "correct": 1, "rate": 0.5}


def test_roman_hindi_rate_ignores_other_romanised_languages():
    rows = [
        row("bacche ghatana kyun nahi seekh paate", "hi", "roman"),
        row("mulanna vajabaki ka samajat nahi", "mr", "roman"),
    ]

    report = score(rows)

    assert report["roman_hindi"]["total"] == 1
    assert report["roman_hindi"]["rate"] == 1.0


def test_english_precision_is_the_share_of_english_calls_that_are_english():
    rows = [
        row("How do I teach place value to the children", "en", "english"),
        row("bacche ghatana kyun nahi seekh paate", "hi", "roman"),
    ]

    report = score(rows)

    assert report["english"]["called_english"] == 1
    assert report["english"]["precision"] == 1.0
    assert report["english"]["recall"] == 1.0


def test_a_mixed_sentence_labelled_english_counts_as_a_correct_english_call():
    rows = [row("Please explain pahade in simple words to the children", "en", "mixed")]

    assert score(rows)["english"]["precision"] == 1.0


def test_an_english_message_called_hindi_lowers_recall_not_precision():
    rows = [
        row("ok", "en", "english"),
        row("What is the best way to teach addition", "en", "english"),
    ]

    report = score(rows)

    assert report["english"]["recall"] == 0.5
    assert report["english"]["precision"] == 1.0


def test_noise_must_stay_undetermined():
    report = score([row("12 + 5 = 17", "und", "noise"), row("???", "und", "noise")])

    assert report["noise"]["rate"] == 1.0


def test_no_rows_of_a_kind_gives_a_zero_rate_not_a_crash():
    report = score([])

    assert report["native"]["rate"] == 0.0
    assert report["pass"] is False


def test_pass_needs_all_three_targets():
    good = [
        row("बच्चे घटाना क्यों नहीं सीख पाते", "hi", "native"),
        row("bacche ghatana kyun nahi seekh paate", "hi", "roman"),
        row("How do I teach place value to the children", "en", "english"),
    ]

    assert score(good)["pass"] is True
    assert score([*good, row("मुझे समझ नहीं आया", "mr", "native")])["pass"] is False


def test_the_targets_are_the_ones_the_plan_states():
    assert (NATIVE_TARGET, ROMAN_HINDI_TARGET, ENGLISH_PRECISION_TARGET) == (0.95, 0.90, 0.98)


def test_load_rows_reads_jsonl_and_rejects_a_bad_row(tmp_path: Path):
    path = tmp_path / "langid.jsonl"
    path.write_text(json.dumps(row("hello there", "en", "english")) + "\n\n", encoding="utf-8")
    assert load_rows(path) == [row("hello there", "en", "english")]

    path.write_text(json.dumps({"text": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_rows(path)
