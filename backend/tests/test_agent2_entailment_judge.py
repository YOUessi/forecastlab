import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    path = ROOT / "eval" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_entailment_judge_prompt_is_quote_only():
    m = load("agent2_entailment_judge.py")
    prompt = m.JUDGE_PROMPT
    assert "Use only the quote text" in prompt
    assert "publisher" in prompt
    assert "outside knowledge" in prompt
    assert "unresolved pronouns" in prompt


def test_entailment_judge_requires_explicit_primary_fallback(monkeypatch):
    m = load("agent2_entailment_judge.py")
    monkeypatch.delenv("ENTAILMENT_JUDGE_API_KEY", raising=False)
    monkeypatch.setattr(m.config, "MODEL_API_KEY", "primary-key")
    try:
        m._judge_config(False)
    except SystemExit as exc:
        assert "--allow-primary-model" in str(exc)
    else:
        raise AssertionError("same-model fallback must be explicit")


def test_entailment_judge_prefers_dedicated_model(monkeypatch):
    m = load("agent2_entailment_judge.py")
    monkeypatch.setenv("ENTAILMENT_JUDGE_API_KEY", "judge-key")
    monkeypatch.setenv("ENTAILMENT_JUDGE_BASE_URL", "https://judge.invalid/v1")
    monkeypatch.setenv("ENTAILMENT_JUDGE_MODEL", "judge-model")
    key, base, model, same = m._judge_config(False)
    assert (key, base, model, same) == (
        "judge-key", "https://judge.invalid/v1", "judge-model", False
    )


def test_calibration_scores_strict_gate_and_thresholds():
    m = load("score_entailment_judge.py")
    human = {"rows": [
        {"case_id": "A", "finding_id": "F1", "human_label": "supported"},
        {"case_id": "A", "finding_id": "F2", "human_label": "partially_supported"},
        {"case_id": "B", "finding_id": "F1", "human_label": "supported"},
        {"case_id": "B", "finding_id": "F2", "human_label": "unsupported"},
    ]}
    judged = {"rows": [
        {"case_id": "A", "finding_id": "F1", "judge": {"label": "entailed", "confidence": 0.98}},
        {"case_id": "A", "finding_id": "F2", "judge": {"label": "partially_entailed", "confidence": 0.94}},
        {"case_id": "B", "finding_id": "F1", "judge": {"label": "entailed", "confidence": 0.70}},
        {"case_id": "B", "finding_id": "F2", "judge": {"label": "entailed", "confidence": 0.55}},
    ]}
    result = m.score(human, judged)
    gate = result["binary_strict_gate"]
    assert gate["tp_supported_accept"] == 2
    assert gate["tn_nonstrict_block"] == 1
    assert gate["fp_nonstrict_accept"] == 1
    assert gate["fn_supported_block"] == 0
    at_09 = next(x for x in result["thresholds"] if x["threshold"] == 0.9)
    assert at_09["accepted"] == 1
    assert at_09["strict_support_among_accepted"] == 1.0
    assert at_09["non_strict_leaks"] == []


def test_nli_label_normalization_without_optional_runtime():
    m = load("agent2_nli_judge.py")
    assert m._label_kind("ENTAILMENT") == "entailment"
    assert m._label_kind("contradiction") == "contradiction"
    assert m._label_kind("LABEL_NEUTRAL") == "neutral"
