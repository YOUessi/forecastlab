from app.benchmarking import percentile, summarize_rows


def test_percentile_interpolates_small_samples():
    assert percentile([10.0, 20.0, 30.0], 0.5) == 20.0
    assert percentile([10.0, 20.0], 0.5) == 15.0
    assert percentile([], 0.95) is None


def test_summary_keeps_failures_and_uses_only_successful_metrics():
    rows = [
        {"status": "ok", "ttft_ms": 10, "total_ms": 110, "tpot_ms": 5, "decode_tok_s": 200},
        {"status": "ok", "ttft_ms": 30, "total_ms": 150, "tpot_ms": 10, "decode_tok_s": 100},
        {"status": "failed", "total_ms": 50},
    ]
    summary = summarize_rows(rows)
    assert summary["requests"] == 3
    assert summary["succeeded"] == 2
    assert summary["failed"] == 1
    assert summary["ttft_ms_p50"] == 20
    assert summary["decode_tok_s_mean"] == 150
