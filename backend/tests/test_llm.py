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
    assert requests[0]["temperature"] == config.MODEL_TEMPERATURE == 0
    assert model.usage == {"calls": 1, "prompt_tokens": 20, "completion_tokens": 10}


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
