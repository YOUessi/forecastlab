"""A later observed outcome scores a forecast without rewriting the forecast."""
from datetime import timedelta

from fastapi.testclient import TestClient

from app.api import create_app
from app.schemas import Forecast, QuestionSpec, RunRecord, utcnow


SOURCE = "https://english.sse.com.cn/news/publications/newsletter/c/10827993/files/a3a75e0b15654ce7a030a6ea803fb916.html"


def record_for_settlement(run_id: str, *, probabilities=None, resolved: bool = True) -> RunRecord:
    now = utcnow()
    question = QuestionSpec(
        question="2026年7月31日科创50指数收盘是否严格高于2207.86点？",
        as_of=now - timedelta(days=40),
        resolve_by=now - timedelta(days=1) if resolved else now + timedelta(days=1),
        resolution_rule="严格高于2207.86点为是，否则为否。",
        resolution_source=SOURCE,
    )
    return RunRecord(
        run_id=run_id, question=question, evidence_mode="import", model="fake",
        status="completed" if probabilities is not None else "insufficient_evidence", stage="done",
        forecast=Forecast(
            status="completed" if probabilities is not None else "insufficient_evidence",
            conclusion="事前判断", probabilities=probabilities,
        ),
    )


def test_settlement_scores_historical_binary_run_and_keeps_original_forecast(tmp_path):
    app = create_app(tmp_path)
    original = record_for_settlement("run_scored", probabilities={"是": .55, "否": .45})
    app.state.store.save(original)
    original_snapshot = (tmp_path / "runs" / "run_scored" / "done.json").read_bytes()
    payload = {"outcome": "否", "source_url": SOURCE, "source_title": "上交所科创50指数月报",
               "observed_value": "1635.96点", "note": "7月31日收盘"}

    with TestClient(app) as client:
        response = client.post("/api/runs/run_scored/settlement", json=payload)
        assert response.status_code == 201
        run = response.json()
        assert run["settlement"]["outcome"] == "否"
        assert run["settlement"]["observed_value"] == "1635.96点"
        assert run["settlement"]["forecast_probabilities"] == {"是": .55, "否": .45}
        assert run["settlement"]["brier_score"] == .3025
        assert run["forecast"]["probabilities"] == original.forecast.probabilities
        assert run["prompt_version"] == "v2"
        assert client.get("/api/runs/run_scored").json()["settlement"]["brier_score"] == .3025
        assert client.get("/api/runs/run_scored/export?format=json").json()["settlement"]["brier_score"] == .3025
        html = client.get("/api/runs/run_scored/export?format=html").text
        assert "实际结果：否" in html and "1635.96点" in html and "0.3025" in html
        assert SOURCE in html
        assert client.post("/api/runs/run_scored/settlement", json=payload).status_code == 409
        summary = client.get("/api/settlements/summary").json()
        assert summary == {"settled_count": 1, "scored_count": 1,
                           "average_brier": .3025, "reference_brier": .25}

    assert (tmp_path / "runs" / "run_scored" / "done.json").read_bytes() == original_snapshot
    assert app.state.store.get("run_scored").forecast.probabilities == {"是": .55, "否": .45}


def test_settlement_validates_deadline_and_outcome(tmp_path):
    app = create_app(tmp_path)
    app.state.store.save(record_for_settlement("run_future", probabilities={"是": .55, "否": .45}, resolved=False))
    app.state.store.save(record_for_settlement("run_past", probabilities={"是": .55, "否": .45}))
    payload = {"outcome": "否", "source_url": SOURCE}

    with TestClient(app) as client:
        assert client.post("/api/runs/run_future/settlement", json=payload).status_code == 409
        assert client.post("/api/runs/run_past/settlement", json={**payload, "outcome": "平"}).status_code == 422
        assert client.post("/api/runs/run_past/settlement", json={"outcome": "否"}).status_code == 422
        assert client.get("/api/settlements/summary").json()["settled_count"] == 0


def test_settlement_can_record_outcome_without_a_probability_or_score(tmp_path):
    app = create_app(tmp_path)
    app.state.store.save(record_for_settlement("run_unscored"))

    with TestClient(app) as client:
        response = client.post("/api/runs/run_unscored/settlement",
                               json={"outcome": "否", "source_url": SOURCE, "observed_value": "1635.96点"})
        assert response.status_code == 201
        assert response.json()["settlement"]["brier_score"] is None
        assert client.get("/api/settlements/summary").json() == {
            "settled_count": 1, "scored_count": 0, "average_brier": None, "reference_brier": .25}
