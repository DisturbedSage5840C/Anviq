import pytest

from app.speech.benchmark import ClipResult, load_manifest, summarise


def _result(provider: str, ref: str, hyp: str, latency: float, seconds: float = 10.0):
    return ClipResult(
        provider=provider,
        clip_id="c",
        condition="clean",
        reference=ref,
        hypothesis=hyp,
        latency_s=latency,
        audio_s=seconds,
    )


def test_summary_averages_error_rates_per_provider():
    results = [
        _result("sarvam", "a b c d", "a b c d", 1.0),
        _result("sarvam", "a b c d", "a x c d", 3.0),
        _result("google", "a b c d", "x y z w", 2.0),
    ]

    summary = {row.provider: row for row in summarise(results, cost_per_hour={"sarvam": 30.0})}

    assert summary["sarvam"].mean_wer == pytest.approx(0.125)
    assert summary["sarvam"].mean_latency_s == pytest.approx(2.0)
    assert summary["sarvam"].clips == 2
    assert summary["google"].mean_wer == pytest.approx(1.0)


def test_summary_cost_scales_with_audio_duration():
    results = [_result("sarvam", "a", "a", 1.0, seconds=1800.0)]

    (row,) = summarise(results, cost_per_hour={"sarvam": 30.0})

    assert row.cost == pytest.approx(15.0)


def test_summary_cost_is_none_when_no_rate_is_known():
    (row,) = summarise([_result("google", "a", "a", 1.0)], cost_per_hour={})

    assert row.cost is None


def test_manifest_rows_become_clips(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "clip,reference,lang,condition\nclips/a.wav,नमस्ते,hi,noisy\n", encoding="utf-8"
    )

    (clip,) = load_manifest(manifest)

    assert clip.path == tmp_path / "clips" / "a.wav"
    assert (clip.reference, clip.lang, clip.condition) == ("नमस्ते", "hi", "noisy")


def test_manifest_missing_a_column_fails_fast(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("clip,reference\na.wav,hello\n", encoding="utf-8")

    with pytest.raises(ValueError, match="lang"):
        load_manifest(manifest)
