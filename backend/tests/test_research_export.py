import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("publish_research", ROOT / "eval/publish_research.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def report(status="reviewed"):
    return {"run_id": "run_test", "model": "fixture", "generated_at": "2026-10-08",
            "quality_status": status, "quality_review": {"checks": ["source scope"]},
            "parts": [{"name": "scenario", "request_id": "request_test", "sections": [{"title": "<script>test</script>", "paragraphs": ["original <analysis> paragraph"], "source_ids": ["B001"]}]}],
            "sources": [{"id": "B001", "title": "source", "source_url": "https://example.org/source", "content_kind": "body", "snapshot_hash": "hash", "excerpt": "private frozen full text"}],
            "calls": [{"request_id": "request_test", "raw_response": "original <analysis> paragraph", "finish_reason": "stop", "input_messages": [{"content": "private source text"}], "status": "succeeded"}]}


def test_candidate_is_not_publishable():
    with pytest.raises(ValueError, match="has not passed"):
        export.render(report("candidate"))


def test_public_export_preserves_response_and_hash_but_omits_private_payload():
    data = export.public_report(report())
    assert data["calls"][0]["raw_response"] == "original <analysis> paragraph"
    assert "input_messages" not in data["calls"][0]
    assert "excerpt" not in data["sources"][0]
    assert data["sources"][0]["snapshot_hash"] == "hash"
    html = export.render(report())
    assert "&lt;script&gt;test&lt;/script&gt;" in html
    assert "original &lt;analysis&gt; paragraph" in html
    assert "<script>" not in html


def test_source_url_cannot_execute_script():
    data = report()
    data["sources"][0]["source_url"] = "javascript:alert(1)"
    with pytest.raises(ValueError, match="invalid source URL"):
        export.render(data)


def test_source_audit_cannot_hide_a_rewritten_or_incomplete_response():
    data = report()
    data["parts"][0]["sections"][0]["paragraphs"] = ["rewritten output"]
    with pytest.raises(ValueError, match="differs from"):
        export.public_report(data)
    data = report()
    data["calls"][0]["finish_reason"] = "length"
    with pytest.raises(ValueError, match="complete original"):
        export.public_report(data)


def test_editorial_correction_is_explicit_and_preserves_raw_response():
    data = report()
    data["parts"][0]["sections"][0]["paragraphs"] = ["audited correction"]
    data["quality_review"]["edits"] = [{"request_id": "request_test", "paragraph_index": 0,
        "original": "original <analysis> paragraph", "revised": "audited correction", "reason": "correct source attribution"}]
    public = export.public_report(data)
    assert public["calls"][0]["raw_response"] == "original <analysis> paragraph"
    assert public["parts"][0]["sections"][0]["paragraphs"] == ["audited correction"]
    data["quality_review"]["edits"][0]["original"] = "fabricated original"
    with pytest.raises(ValueError, match="untraceable editorial"):
        export.public_report(data)
