"""One DeepSeek call on the same frozen question and evidence pack."""
import argparse
import json
import time
import sys
from pathlib import Path
from pydantic import BaseModel, Field
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import config
from app.llm import ModelClient
from app.schemas import QuestionSpec, Evidence


class BaselinePrediction(BaseModel):
    probability_yes: float = Field(ge=0, le=1)
    conclusion: str
    evidence_ids: list[str]
    limitations: list[str]


def main():
    parser = argparse.ArgumentParser(description="Same-model, same-evidence single-agent baseline")
    parser.add_argument("pack", type=Path, help="JSON containing question and evidence")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.pack.read_text(encoding="utf-8"))
    question = QuestionSpec.model_validate(data["question"])
    evidence = [Evidence.model_validate(item) for item in data["evidence"]]
    if question.mode != "binary":
        raise SystemExit("基线只适用于二元事件")
    client = ModelClient()
    start = time.monotonic()
    result = client.complete("single-agent-baseline", {"question": question.model_dump(mode="json"), "evidence": [e.model_dump(mode="json") for e in evidence]}, BaselinePrediction,
                             "在一次调用中直接判断二元事件。只引用给出的证据 ID；输出概率为主观、未校准。")
    missing = set(result.evidence_ids) - {e.id for e in evidence}
    if missing:
        raise SystemExit(f"基线引用不存在：{', '.join(sorted(missing))}")
    output = {"question_id": question.id, "model": config.MODEL_NAME, "prediction": result.model_dump(), "usage": client.usage, "elapsed_seconds": round(time.monotonic() - start, 2)}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
