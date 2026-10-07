import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_interrater_perfect_and_partial_agreement():
    mod = load("score_interrater", "eval/score_interrater.py")
    base = {"rows": [
        {"case_id": "C1", "finding_id": "F1", "claim": "a", "human_label": "supported"},
        {"case_id": "C1", "finding_id": "F2", "claim": "b", "human_label": "partially_supported"},
        {"case_id": "C2", "finding_id": "F1", "claim": "c", "human_label": "unsupported"},
        {"case_id": "C2", "finding_id": "F2", "claim": "d", "human_label": "unclear"},
    ]}
    same = {"rows": [dict(row) for row in base["rows"]]}
    assert mod.score(base, same)["raw_agreement"] == 1.0
    assert mod.score(base, same)["cohen_kappa_4class"] == 1.0
    changed = {"rows": [dict(row) for row in base["rows"]]}
    changed["rows"][1]["human_label"] = "supported"
    result = mod.score(base, changed)
    assert result["raw_agreement"] == 0.75
    assert len(result["disagreements"]) == 1


def test_tavily_summary_handles_empty_and_authoritative_metrics():
    mod = load("tavily_quality", "eval/tavily_quality.py")
    rows = [
        {"status": "completed", "selected_evidence": 2, "task_count": 2, "task_successes": 2,
         "query_coverage": 1.0, "body_count": 1, "snippet_only_count": 1, "date_metadata_count": 1,
         "authoritative_hit": True, "exclusion_count": 0, "duplicate_aliases": 1,
         "possible_same_source_pairs": 0, "evidence": [{}, {}]},
        {"status": "failed", "selected_evidence": 0, "task_count": 2, "task_successes": 0,
         "query_coverage": 0.0, "body_count": 0, "snippet_only_count": 0, "date_metadata_count": 0,
         "authoritative_hit": False, "exclusion_count": 1, "duplicate_aliases": 0,
         "possible_same_source_pairs": 0, "evidence": []},
    ]
    result = mod.summarize(rows)
    assert result["case_with_evidence_rate"] == 0.5
    assert result["task_success_rate"] == 0.5
    assert result["body_rate"] == 0.5
    assert result["authoritative_hit_rate"] == 0.5


def test_reviewer_ui_saves_blind_label(tmp_path):
    mod = load("reviewer_ui", "eval/reviewer_ui.py")
    packet = tmp_path / "packet.json"
    output = tmp_path / "reviewed.json"
    packet.write_text(json.dumps({"rows": [{
        "case_id": "C1", "finding_id": "F1", "relation": "background", "claim": "claim",
        "limitation": "limit", "citations": [{"evidence_id": "E1", "source_title": "source", "paragraph_id": "B1", "quote": "quote"}],
        "human_label": None, "human_notes": ""
    }]}), encoding="utf-8")
    with TestClient(mod.create_app(packet, output)) as client:
        assert client.get("/api/status").json()["done"] == 0
        saved = client.post("/api/rows/0", json={"human_label": "supported", "human_notes": "direct"})
        assert saved.status_code == 200 and saved.json()["done"] == 1
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["rows"][0]["human_label"] == "supported"
    assert data["rows"][0]["human_notes"] == "direct"
