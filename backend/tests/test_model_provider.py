from types import SimpleNamespace

from app import config
from app.llm import ModelClient
from app.schemas import QuestionAnalysis


def _response(content: str):
    return SimpleNamespace(
        model="Model",
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))],
    )


def test_vllm_mt_settings_use_openai_compatible_local_defaults():
    settings = config.resolve_model_settings({"FORECASTLAB_MODEL_PROVIDER": "vllm_mt"})
    assert settings["provider"] == "vllm_mt"
    assert settings["base_url"] == "http://127.0.0.1:18014/v1"
    assert settings["model"] == "Model"
    assert settings["api_key"] == "EMPTY"
    assert settings["requires_key"] is False
    assert settings["timeout_seconds"] == 180


def test_auto_preserves_qwen_then_deepseek_precedence():
    qwen = config.resolve_model_settings({
        "QWEN_API_KEY": "q-key",
        "DEEPSEEK_API_KEY": "d-key",
    })
    assert qwen["provider"] == "qwen"
    assert qwen["api_key"] == "q-key"
    assert qwen["model"] == "qwen3.8-flash"

    deepseek = config.resolve_model_settings({"DEEPSEEK_API_KEY": "d-key"})
    assert deepseek["provider"] == "deepseek"
    assert deepseek["api_key"] == "d-key"


def test_vllm_mt_does_not_inherit_qwen_thinking_extra_body(monkeypatch):
    requests = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return _response('{"normalized_question":"测试问题","search_queries":["检索词"]}')

    monkeypatch.setattr(config, "MODEL_PROVIDER", "vllm_mt")
    monkeypatch.setattr(config, "MODEL_REQUIRES_KEY", False)
    monkeypatch.setattr(config, "MODEL_API_KEY", "EMPTY")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "http://127.0.0.1:18014/v1")
    monkeypatch.setattr(config, "MODEL_NAME", "Model")
    monkeypatch.setattr(config, "MODEL_TIMEOUT_SECONDS", 180)
    monkeypatch.setattr(
        "app.llm.OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    model = ModelClient()
    result = model.complete("question", {"question": "测试问题"}, QuestionAnalysis, "测试指令")

    assert result.search_queries == ["检索词"]
    assert "extra_body" not in requests[0]


def test_model_configured_accepts_keyless_vllm_mt(monkeypatch):
    monkeypatch.setattr(config, "MODEL_REQUIRES_KEY", False)
    monkeypatch.setattr(config, "MODEL_API_KEY", "EMPTY")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "http://127.0.0.1:18014/v1")
    monkeypatch.setattr(config, "MODEL_NAME", "Model")
    assert config.model_configured() is True


def test_health_reports_provider_without_exposing_key(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.api import create_app
    monkeypatch.setattr(config, "MODEL_PROVIDER", "vllm_mt")
    monkeypatch.setattr(config, "MODEL_REQUIRES_KEY", False)
    monkeypatch.setattr(config, "MODEL_API_KEY", "super-secret")
    monkeypatch.setattr(config, "MODEL_NAME", "Model")
    with TestClient(create_app(tmp_path)) as client:
        body = client.get("/api/health").json()
    assert body["model_provider"] == "vllm_mt"
    assert body["model_configured"] is True
    assert "super-secret" not in str(body)
