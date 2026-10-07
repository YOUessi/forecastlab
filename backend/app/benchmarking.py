from __future__ import annotations

import math
import statistics


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def summarize_rows(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status") == "ok"]

    def vals(key: str) -> list[float]:
        return [float(r[key]) for r in ok if r.get(key) is not None]

    ttft = vals("ttft_ms")
    total = vals("total_ms")
    tpot = vals("tpot_ms")
    decode = vals("decode_tok_s")
    return {
        "requests": len(rows),
        "succeeded": len(ok),
        "failed": len(rows) - len(ok),
        "ttft_ms_p50": percentile(ttft, 0.50),
        "ttft_ms_p95": percentile(ttft, 0.95),
        "total_ms_p50": percentile(total, 0.50),
        "total_ms_p95": percentile(total, 0.95),
        "tpot_ms_p50": percentile(tpot, 0.50),
        "decode_tok_s_mean": statistics.fmean(decode) if decode else None,
    }
