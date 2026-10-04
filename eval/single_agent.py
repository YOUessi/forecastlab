"""One-call single-agent predictor, used as the evaluation baseline.

Two arms share the same schema and differ only in whether the frozen evidence
pack is put in the payload, so the comparison isolates the effect of evidence:

    with_evidence=True    same question, same evidence as the full pipeline
    with_evidence=False   question only, the model must rely on its own knowledge
"""
import sys
import time
from pathlib import Path
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.schemas import Evidence, QuestionSpec  # noqa: E402

WITH_EVIDENCE = (
    "在一次调用中直接判断二元事件，只使用给出的证据。"
    "只引用给出的证据 ID，不要编造编号；输出概率为主观、未校准。"
)
WITHOUT_EVIDENCE = (
    "在一次调用中直接判断二元事件，不使用任何外部证据，只依据你自己已有的知识。"
    "evidence_ids 必须为空数组；输出概率为主观、未校准。"
)


class BaselinePrediction(BaseModel):
    probability_yes: float = Field(ge=0, le=1)
    conclusion: str
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def usage_delta(before: dict, after: dict) -> dict:
    return {key: after.get(key, 0) - before.get(key, 0) for key in after}


def predict(question: QuestionSpec, evidence: list[Evidence], client, *, with_evidence: bool = True):
    """Return (prediction, metrics). Metrics carry the usage of this call only."""
    payload = {"question": question.model_dump(mode="json")}
    if with_evidence:
        payload["evidence"] = [item.model_dump(mode="json") for item in evidence]
        instructions = WITH_EVIDENCE
    else:
        instructions = WITHOUT_EVIDENCE
    valid_ids = {item.id for item in evidence} if with_evidence else set()
    before = dict(client.usage)
    started = time.monotonic()
    result = client.complete("single-agent-baseline", payload, BaselinePrediction, instructions)
    missing = set(result.evidence_ids) - valid_ids
    if missing:
        raise ValueError(f"基线引用了不存在的证据：{', '.join(sorted(missing))}")
    return result, {
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "usage": usage_delta(before, dict(client.usage)),
    }
