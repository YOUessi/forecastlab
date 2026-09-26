"""A fictional classroom exercise. None of these items are external evidence."""
from datetime import datetime, timezone
import hashlib
from .schemas import QuestionSpec, Evidence


DEMO_QUESTION = QuestionSpec(
    id="Q-DEMO", question="青岚开源社区能否在 2026 年 11 月 15 日前发布 V2 正式版？",
    as_of=datetime(2026, 9, 26, 8, tzinfo=timezone.utc),
    resolve_by=datetime(2026, 11, 15, 23, 59, tzinfo=timezone.utc),
    resolution_rule="以青岚开源社区官方版本页出现 V2 正式版且可下载为是，否则为否。",
    resolution_source="教学虚构情境：不存在真实结算来源",
)


def demo_evidence() -> list[Evidence]:
    rows = [
        ("项目路线图", "教学虚构材料：项目组计划在 11 月中旬发布 V2，核心功能已进入集成阶段。", "项目组"),
        ("测试记录", "教学虚构材料：9 月回归测试发现两个高优先级兼容问题，修复时间尚未确认。", "测试组"),
        ("合作方说明", "教学虚构材料：托管合作方可提供额外测试资源，但要在 10 月前确认排期。", "合作方"),
    ]
    return [Evidence(
        id=f"E{i:03}", file_id=f"exercise:{i}", title=title, publisher=publisher,
        retrieved_at=DEMO_QUESTION.as_of, excerpt=excerpt, claim=excerpt,
        content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
        source_type="exercise", source_group=f"exercise-{i}", date_status="synthetic",
    ) for i, (title, excerpt, publisher) in enumerate(rows, 1)]


def demo_output(role: str, actor_id: str | None = None, round_number: int = 1) -> dict:
    if role == "question":
        return {"normalized_question": DEMO_QUESTION.question, "search_queries": ["青岚开源社区 V2 路线图", "青岚开源社区 V2 测试", "青岚开源社区 合作方"], "caveats": ["教学虚构情境；不进行真实搜索"]}
    if role == "evidence":
        return {"summary": "教学材料有发布目标与测试阻碍，尚无实际修复完成证明。", "evidence_ids": ["E001", "E002", "E003"],
                "conflicts": ["发布目标与未解决兼容问题之间存在张力"], "gaps": ["最新复测记录", "合作方最终排期"]}
    if role == "world":
        return {
            "state_version": 0, "summary": "教学虚构情境：V2 处于集成阶段，兼容问题可能影响发布日期。",
            "variables": {"release_readiness": "集成中", "compatibility": "两个高优先级问题未解决", "partner_slot": "待确认"},
            "relations": ["测试进度影响发布决定", "合作方资源可能缩短验证时间"],
            "actors": [
                {"id": "A1", "name": "项目组", "goal": "按期发布稳定版本", "resources": ["开发人员"], "constraints": ["兼容问题"], "visible_evidence_ids": ["E001", "E002"]},
                {"id": "A2", "name": "测试组", "goal": "避免高优先级缺陷进入正式版", "resources": ["回归测试"], "constraints": ["测试时间"], "visible_evidence_ids": ["E002"]},
                {"id": "A3", "name": "合作方", "goal": "提供可用的测试资源", "resources": ["托管环境"], "constraints": ["排期"], "visible_evidence_ids": ["E003"]},
            ],
            "evidence_refs": ["E001", "E002", "E003"],
            "assumptions": [{"id": "H001", "created_by": "model", "parent_ids": ["E002"], "content": "兼容问题可以在发布前修复", "rationale": "材料未提供修复时长"}],
        }
    if role == "actor":
        choices = {
            1: {"A1": ("优先修复兼容问题", "把有限开发时间投入阻塞项", "提高稳定发布机会", ["E002"]), "A2": ("扩大回归测试", "尽早暴露残留问题", "可能延长验证周期", ["E002"]), "A3": ("预留测试环境", "在排期截止前锁定资源", "缓解测试瓶颈", ["E003"])},
            2: {"A1": ("按测试反馈决定发布范围", "保留缩减功能的选项", "增加按时发布弹性", ["E001", "E002"]), "A2": ("复测两个兼容问题", "确认修复是否有效", "决定是否建议发布", ["E002"]), "A3": ("继续提供测试环境", "支持二轮验证", "减少环境等待", ["E003"])},
        }
        action, rationale, impact, refs = choices[round_number][actor_id]
        return {"id": f"M{round_number}-{actor_id}", "created_by": actor_id, "parent_ids": [], "actor_id": actor_id, "round": round_number,
                "parent_state": round_number - 1, "action": action, "rationale_summary": rationale, "expected_impact": impact,
                "evidence_ids": refs, "assumption_ids": ["H001"] if actor_id == "A1" else [], "kind": "simulation"}
    if role == "environment":
        return {"id": f"S{round_number}", "created_by": "environment", "parent_ids": [f"M{round_number}-A{i}" for i in (1, 2, 3)],
                "round": round_number, "parent_state": round_number - 1, "next_state": round_number,
                "summary": "模拟：主体行动改善验证条件，但兼容问题是否解决仍未知。" if round_number == 1 else "模拟：项目组准备依据复测结果选择正式发布或延期。",
                "state_changes": {"release_readiness": "待二轮复测" if round_number == 1 else "等待最终决策"},
                "conflicts": ["按时发布目标与充分测试时间存在冲突"], "unresolved": ["兼容问题实际修复情况未知"],
                "evidence_ids": ["E001", "E002", "E003"], "assumption_ids": ["H001"], "kind": "simulation"}
    if role == "review":
        return {"status": "qualified", "issues": [{"severity": "medium", "claim": "兼容问题将按时修复", "explanation": "这是 H001 假设，现有材料没有确认修复完成。", "affected_ids": ["H001"]}],
                "unsupported_claims": [], "missing_evidence": ["最新复测记录"]}
    if role == "forecast":
        return {"status": "completed", "conclusion": "教学示例：如兼容问题按时修复，项目存在按期发布的路径；结果高度依赖复测。",
                "probabilities": {"是": 0.62, "否": 0.38}, "calibrated": False,
                "supporting": [{"text": "路线图设定了 11 月中旬的目标。", "evidence_ids": ["E001"]}, {"text": "合作方有条件提供测试资源。", "evidence_ids": ["E003"]}],
                "opposing": [{"text": "兼容问题尚未确认修复。", "evidence_ids": ["E002"]}],
                "key_assumptions": ["H001"], "scenarios": ["复测通过后按期发布", "高优先级问题持续存在而延期"],
                "limitations": ["全部材料与数值均为教学虚构，不能视为真实预测。", "主观概率未经校准。"],
                "new_information": ["兼容问题的最新复测记录", "合作方最终排期"]}
    raise ValueError(role)
