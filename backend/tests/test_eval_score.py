"""Brier Skill Score and table handling for eval/score_table.py and eval/run_suite.py."""
import importlib.util
import json
from pathlib import Path

EVAL = Path(__file__).resolve().parents[2] / "eval"


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = load_module("score_table")


def table():
    return [
        {"id": "C1", "category": "tech", "outcome": 1, "full_p": 0.8},
        {"id": "C2", "category": "tech", "outcome": 0, "full_p": 0.2},
        {"id": "C3", "category": "sport", "outcome": 1, "full_p": 0.6},
        {"id": "C4", "category": "sport", "outcome": 0, "full_p": 0.4},
    ]


def test_brier_skill_against_half_and_base_rate():
    summary = score.summarize(table(), "full_p")
    assert summary["settled_n"] == 4
    assert summary["valid_n"] == 4
    assert summary["coverage"] == 1
    assert summary["brier_on_valid"] == 0.1
    assert summary["brier_reference_half"] == 0.25
    assert summary["base_rate"] == 0.5
    assert summary["brier_skill_vs_half"] == 0.6
    assert summary["brier_skill_vs_base_rate"] == 0.6


def test_abstention_lowers_coverage_but_keeps_scoring_on_answered_rows():
    rows = table()
    rows[1]["full_p"] = None
    summary = score.summarize(rows, "full_p")
    assert summary["valid_n"] == 3
    assert summary["coverage"] == 0.75
    assert round(summary["brier_on_valid"], 4) == 0.12
    assert round(summary["brier_with_half_fallback"], 4) == 0.1525
    # the reference is computed on the answered rows too, so abstaining on a
    # hard case cannot inflate the skill score
    assert summary["brier_reference_half"] == 0.25


def test_skill_is_none_when_the_reference_is_perfect():
    rows = [{"id": "C1", "outcome": 1, "full_p": 0.7}]
    summary = score.summarize(rows, "full_p")
    assert summary["base_rate"] == 1.0
    assert summary["brier_reference_base_rate"] == 0
    assert summary["brier_skill_vs_base_rate"] is None
    assert round(summary["brier_skill_vs_half"], 6) == 0.64


def test_perfect_and_climatology_forecasts_sit_at_the_ends():
    rows = table()
    perfect = [dict(row, perfect_p=float(row["outcome"])) for row in rows]
    climatology = [dict(row, clim_p=0.5) for row in rows]
    assert score.summarize(perfect, "perfect_p")["brier_skill_vs_half"] == 1
    assert score.summarize(climatology, "clim_p")["brier_skill_vs_half"] == 0


def test_probability_columns_follow_first_appearance():
    rows = [
        {"id": "C1", "outcome": 1, "full_p": 0.5, "baseline_p": 0.5},
        {"id": "C2", "outcome": 0, "no_evidence_p": 0.5},
    ]
    assert score.probability_columns(rows) == ["full_p", "baseline_p", "no_evidence_p"]


def test_rows_can_be_wrapped_in_a_report_object(tmp_path):
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"suite": "demo", "frozen": {"model": "x"}, "rows": table()}), encoding="utf-8")
    rows = score.load_rows(path)
    assert len(rows) == 4
    assert score.summarize_columns(rows, ["full_p"])["full_p"]["brier_skill_vs_half"] == 0.6


def test_grouping_splits_by_category():
    groups = score.grouped(table(), "category")
    assert set(groups) == {"sport", "tech"}
    assert len(groups["tech"]) == 2


def test_run_suite_validates_cases(tmp_path):
    suite = load_module("run_suite")
    path = tmp_path / "suite.json"
    good = {
        "name": "unit",
        "cases": [{
            "id": "C1", "category": "tech", "outcome": 1,
            "question": {"question": "Python 3.13 会在 2024-10-01 前发布吗？",
                         "as_of": "2024-09-10T00:00:00Z",
                         "resolve_by": "2024-10-01T23:59:00Z",
                         "resolution_rule": "以 python.org 正式版页面为准。",
                         "mode": "binary"},
        }],
    }
    path.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    meta, cases = suite.load_suite(path)
    assert meta["name"] == "unit" and len(cases) == 1
    assert suite.yes_outcome(suite.QuestionSpec.model_validate(cases[0]["question"])) == "是"

    bad = {"cases": [{"id": "C2", "question": global_question()}]}
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    try:
        suite.load_suite(path)
        raise AssertionError("outcome 必须被校验")
    except SystemExit:
        pass



def test_historical_evidence_date_coverage_flags_unknown_cutoff_availability():
    validate = load_module("validate_cases")
    as_of = validate.parse_ts("2025-01-31T23:59:00Z")
    status = validate.publication_date_coverage([
        {"source_url": "https://example.org/known", "published_at": "2025-01-01T00:00:00Z"},
        {"source_url": "https://example.org/unknown", "published_at": None},
    ], as_of)
    assert status["known"] == 1 and status["total"] == 2
    assert status["coverage"] == 0.5
    assert status["strict_cutoff_ready"] is False
    assert status["missing"] == ["https://example.org/unknown"]


def test_historical_evidence_date_coverage_accepts_all_pre_cutoff_dates():
    validate = load_module("validate_cases")
    as_of = validate.parse_ts("2025-01-31T23:59:00Z")
    status = validate.publication_date_coverage([
        {"source_url": "https://example.org/a", "published_at": "2025-01-01T00:00:00Z"},
        {"source_url": "https://example.org/b", "published_at": "2025-01-15T00:00:00Z"},
    ], as_of)
    assert status["strict_cutoff_ready"] is True
    assert status["coverage"] == 1.0

def global_question():
    return {"question": "某某事件会在 2024-10-01 前发生吗？", "as_of": "2024-09-10T00:00:00Z",
            "resolve_by": "2024-10-01T23:59:00Z", "resolution_rule": "以官方公告为准。", "mode": "binary"}
