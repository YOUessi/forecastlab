from types import SimpleNamespace
import httpx
from openai import APIConnectionError
from app import config
from app.llm import ModelClient
from app.schemas import QuestionAnalysis


def response(content: str):
    return SimpleNamespace(
        model="qwen3.8-flash",
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))],
    )


def test_qwen_flash_disables_thinking_for_json_calls(monkeypatch):
    requests = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return response('{"normalized_question":"测试问题","search_queries":["检索词"]}')

    monkeypatch.setattr(config, "MODEL_API_KEY", "test-only")
    monkeypatch.setattr(config, "MODEL_NAME", "qwen3.8-flash")
    monkeypatch.setattr("app.llm.OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    model = ModelClient()
    result = model.complete("question", {"question": "测试问题"}, QuestionAnalysis, "测试指令")
    assert result.search_queries == ["检索词"]
    assert requests[0]["extra_body"] == {"enable_thinking": False}
    assert model.usage == {"calls": 1, "prompt_tokens": 20, "completion_tokens": 10}


def test_local_vllm_uses_chat_template_protocol_and_configured_output_budget(monkeypatch):
    monkeypatch.delenv("FORECASTLAB_LOCAL_JSON_MODE", raising=False)
    requests = []
    constructor = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return response('{"normalized_question":"test question","search_queries":["test"]}')

    def fake_client(**kwargs):
        constructor.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    monkeypatch.setattr(config, "MODEL_API_KEY", "test-only")
    monkeypatch.setattr(config, "MODEL_NAME", "qwen3-8b")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "http://127.0.0.1:18008/v1")
    monkeypatch.setenv("FORECASTLAB_MODEL_TIMEOUT", "120")
    monkeypatch.setenv("FORECASTLAB_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setattr("app.llm.OpenAI", fake_client)
    ModelClient().complete("question", {"question": "test"}, QuestionAnalysis, "test")
    assert constructor[0]["base_url"] == "http://127.0.0.1:18008/v1"
    assert constructor[0]["timeout"] == 120
    assert requests[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert requests[0]["temperature"] == 0
    assert requests[0]["max_tokens"] == 2048
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[0]["response_format"]["json_schema"]["name"] == "QuestionAnalysis"


def test_local_prompt_json_still_rejects_invalid_schema(monkeypatch):
    requests = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                return response('{"search_queries":[]}')
            return response('{"normalized_question":"test","search_queries":["source"]}')

    monkeypatch.setattr(config, "MODEL_API_KEY", "test-only")
    monkeypatch.setattr(config, "MODEL_NAME", "qwen3-8b")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "http://127.0.0.1:18048/v1")
    monkeypatch.setenv("FORECASTLAB_LOCAL_JSON_MODE", "prompt")
    monkeypatch.setattr("app.llm.OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    client = ModelClient()
    result = client.complete("question", {}, QuestionAnalysis, "test")
    assert result.normalized_question == "test"
    assert len(requests) == 2
    assert "response_format" not in requests[0]
    assert client.call_records[0].status == "failed"
    assert client.call_records[1].status == "succeeded"


def test_connection_error_retries_and_preserves_budget(monkeypatch):
    calls = 0

    class FakeCompletions:
        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise APIConnectionError(request=httpx.Request("POST", "https://example.test/chat"))
            return response('{"normalized_question":"测试问题","search_queries":["检索词"]}')

    monkeypatch.setattr(config, "MODEL_API_KEY", "test-only")
    monkeypatch.setattr(config, "MODEL_NAME", "qwen3.8-flash")
    monkeypatch.setattr("app.llm.OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    monkeypatch.setattr("app.llm.time.sleep", lambda _: None)
    model = ModelClient()
    model.complete("question", {"question": "测试问题"}, QuestionAnalysis, "测试指令")
    assert calls == 3
    assert model.usage["calls"] == 3


def test_local_reasoning_can_be_enabled_without_relaxing_schema(monkeypatch):
    requests = []
    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return response('{"normalized_question":"test","search_queries":["source"]}')
    monkeypatch.setattr(config, "MODEL_API_KEY", "test-only")
    monkeypatch.setattr(config, "MODEL_NAME", "qwen3-8b")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "http://127.0.0.1:18048/v1")
    monkeypatch.setenv("FORECASTLAB_ENABLE_THINKING", "true")
    monkeypatch.delenv("FORECASTLAB_LOCAL_JSON_MODE", raising=False)
    monkeypatch.setattr("app.llm.OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    result = ModelClient().complete("question", {}, QuestionAnalysis, "test")
    assert result.normalized_question == "test"
    assert requests[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
    assert requests[0]["response_format"]["type"] == "json_schema"
