from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
_data_path = Path(os.getenv("FORECASTLAB_DATA_DIR", "data"))
DATA_DIR = (_data_path if _data_path.is_absolute() else ROOT / _data_path).resolve()


def resolve_model_settings(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """Resolve one OpenAI-compatible model backend without changing upper-layer agent code."""
    values = os.environ if env is None else env
    requested = str(values.get("FORECASTLAB_MODEL_PROVIDER", "auto")).strip().lower() or "auto"
    allowed = {"auto", "qwen", "deepseek", "vllm_mt"}
    if requested not in allowed:
        raise ValueError(
            "FORECASTLAB_MODEL_PROVIDER must be one of auto, qwen, deepseek, vllm_mt"
        )

    qwen_key = str(values.get("QWEN_API_KEY", ""))
    deepseek_key = str(values.get("DEEPSEEK_API_KEY", ""))

    if requested == "auto":
        provider = "qwen" if qwen_key else "deepseek"
    else:
        provider = requested

    if provider == "qwen":
        return {
            "provider": "qwen",
            "api_key": qwen_key,
            "base_url": str(
                values.get(
                    "QWEN_BASE_URL",
                    "https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1",
                )
            ),
            "model": str(values.get("QWEN_MODEL", "qwen3.8-flash")),
            "requires_key": True,
            "timeout_seconds": int(values.get("FORECASTLAB_MODEL_TIMEOUT", "45")),
        }

    if provider == "deepseek":
        return {
            "provider": "deepseek",
            "api_key": deepseek_key,
            "base_url": str(values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")),
            "model": str(values.get("DEEPSEEK_MODEL", "deepseek-flash")),
            "requires_key": True,
            "timeout_seconds": int(values.get("FORECASTLAB_MODEL_TIMEOUT", "45")),
        }

    return {
        "provider": "vllm_mt",
        "api_key": str(values.get("VLLM_MT_API_KEY", "")) or "EMPTY",
        "base_url": str(values.get("VLLM_MT_BASE_URL", "http://127.0.0.1:18014/v1")),
        "model": str(values.get("VLLM_MT_MODEL", "Model")),
        "requires_key": False,
        "timeout_seconds": int(values.get("VLLM_MT_TIMEOUT", "180")),
    }


_MODEL = resolve_model_settings()
MODEL_PROVIDER = str(_MODEL["provider"])
MODEL_API_KEY = str(_MODEL["api_key"])
MODEL_BASE_URL = str(_MODEL["base_url"]).rstrip("/")
MODEL_NAME = str(_MODEL["model"])
MODEL_REQUIRES_KEY = bool(_MODEL["requires_key"])
MODEL_TIMEOUT_SECONDS = int(_MODEL["timeout_seconds"])


def model_configured() -> bool:
    if MODEL_REQUIRES_KEY:
        return bool(MODEL_API_KEY)
    return bool(MODEL_BASE_URL and MODEL_NAME)


TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
MAX_CALLS = int(os.getenv("FORECASTLAB_MAX_CALLS", "18"))
MAX_SECONDS = int(os.getenv("FORECASTLAB_MAX_SECONDS", "300"))
MODEL_TEMPERATURE = float(os.getenv("FORECASTLAB_MODEL_TEMPERATURE", "0"))
if not 0 <= MODEL_TEMPERATURE <= 2:
    raise ValueError("FORECASTLAB_MODEL_TEMPERATURE 必须在 0–2 之间")
