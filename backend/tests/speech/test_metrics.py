import pytest

from app.speech.metrics import cer, wer


def test_identical_text_has_zero_error() -> None:
    assert wer("दो अंकों का घटाना", "दो अंकों का घटाना") == 0.0
    assert cer("दो अंकों का घटाना", "दो अंकों का घटाना") == 0.0


def test_wer_counts_substitutions_over_reference_words() -> None:
    assert wer("a b c d", "a x c d") == pytest.approx(0.25)


def test_wer_counts_insertions_and_deletions() -> None:
    assert wer("a b c", "a c") == pytest.approx(1 / 3)
    assert wer("a b", "a b c") == pytest.approx(1 / 2)


def test_cer_works_on_characters() -> None:
    assert cer("abcd", "abxd") == pytest.approx(0.25)


def test_comparison_ignores_case_punctuation_and_extra_spaces() -> None:
    assert wer("Hello,  World!", "hello world") == 0.0
    assert wer("क्या यह सही है?", "क्या यह सही है") == 0.0


def test_empty_reference_is_all_error_unless_hypothesis_is_empty_too() -> None:
    assert wer("", "") == 0.0
    assert wer("", "something") == 1.0
