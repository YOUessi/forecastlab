from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
_data_path = Path(os.getenv("FORECASTLAB_DATA_DIR", "data"))
DATA_DIR = (_data_path if _data_path.is_absolute() else ROOT / _data_path).resolve()
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
MODEL_API_KEY = QWEN_API_KEY or os.getenv("DEEPSEEK_API_KEY", "")
MODEL_BASE_URL = (os.getenv("QWEN_BASE_URL", "https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1")
                  if QWEN_API_KEY else os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
MODEL_NAME = (os.getenv("QWEN_MODEL", "qwen3.8-flash")
              if QWEN_API_KEY else os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
MAX_CALLS = int(os.getenv("FORECASTLAB_MAX_CALLS", "18"))
MAX_SECONDS = int(os.getenv("FORECASTLAB_MAX_SECONDS", "300"))
# Off by default: the shadow forecast is experiment instrumentation and costs one extra
# model call per evidence-only run, so the product path stays at one forecast call.
SHADOW_FULL = os.getenv("FORECASTLAB_SHADOW", "0").strip().lower() not in {"", "0", "false", "no"}
