"""Explicit SAO workflow. Each node owns a single stage output."""
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from .schemas import (QuestionSpec, QuestionAnalysis, Evidence, EvidenceAssessment, WorldState, ActorAction, SimulationStep,
                      Review, ReviewIssue, Forecast, RunRecord, utcnow)
from .sources import online_search
from .llm import BudgetExceeded, ModelClient
from .demo import demo_output
from . import config


class FlowState(TypedDict, total=False):
    question: dict
    question_analysis: dict
    evidence: list[dict]
    evidence_assessment: dict
    world: dict
    actions: list[dict]
    simulation: list[dict]
    review: dict
    forecast: dict


def evidence_for_model(items: list[Evidence], limit: int = 2400) -> list[dict]:
    """Keep model context bounded while retaining complete evidence in snapshots."""
    return [{**e.model_dump(mode="json", exclude={"snapshot_path", "content_hash"}),
             "excerpt": e.excerpt[:limit]} for e in items]


def check_ids(ids: list[str], valid: set[str], label: str):
    missing = set(ids) - valid
    if missing:
        raise ValueError(f"{label}引用不存在：{', '.join(sorted(missing))}")


def validate_forecast(forecast: Forecast, question: QuestionSpec, evidence: list[Evidence], world: WorldState,
                      simulation: list[SimulationStep], review: Review):
    evidence_ids = {e.id for e in evidence}
    assumption_ids = {a.id for a in world.assumptions}
    simulation_ids = {s.id for s in simulation}
    for claim in forecast.supporting + forecast.opposing:
        check_ids(claim.evidence_ids, evidence_ids, "报告证据")
        check_ids(claim.assumption_ids, assumption_ids, "报告假设")
        check_ids(claim.simulation_ids, simulation_ids, "报告模拟")
        if not (claim.evidence_ids or claim.assumption_ids or claim.simulation_ids):
            raise ValueError("报告主张没有可展开的依据")
    check_ids(forecast.key_assumptions, assumption_ids, "关键假设")
    if question.mode == "scenario" or review.status == "blocked" or not evidence:
        forecast.probabilities = None
        forecast.status = "scenario_only" if question.mode == "scenario" else "insufficient_evidence"
    if forecast.probabilities is not None:
        if set(forecast.probabilities) != set(question.outcomes):
            raise ValueError("概率结果选项与问题不一致")
        if any(p < 0 or p > 1 for p in forecast.probabilities.values()) or abs(sum(forecast.probabilities.values()) - 1) > .001:
            raise ValueError("概率须在 0–1 且合计为 1")
    elif forecast.status == "completed":
        forecast.status = "insufficient_evidence"


STAGE_NODES = (
    ("question", "define_question"), ("evidence", "retrieve"), ("world", "model_world"),
    ("simulation", "simulate"), ("review", "audit"), ("forecast", "synthesize"),
)


def build_graph(record: RunRecord, imported: list[Evidence], model: ModelClient | None, data_dir, *, start_at: str = "define_question"):
    def ask(role, payload, schema, instructions, *, actor_id=None, round_number=1):
        if record.demo:
            return schema.model_validate(demo_output(role, actor_id, round_number))
        return model.complete(role, payload, schema, instructions)

    def question_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        analysis = ask("question", {"question": question.model_dump(mode="json")}, QuestionAnalysis,
                       "用户已确认预测目标和结算规则。用一句话规范化问题，给最多 3 个适合寻找原始资料的检索词；不要自行更改日期或结算条件。")
        analysis.search_queries = [q[:400] for q in analysis.search_queries[:3]]
        return {"question_analysis": analysis.model_dump(mode="json")}

    def evidence_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        if record.evidence_mode == "online":
            queries = QuestionAnalysis.model_validate(state["question_analysis"]).search_queries
            items = online_search(question, data_dir, queries)
        else:
            items = imported
        assessment = ask("evidence", {"question": state["question"], "evidence": evidence_for_model(items)}, EvidenceAssessment,
                         "归纳资料冲突和缺口，只引用实际存在的证据编号。搜索摘要不是全文证据；不可编造新来源。")
        check_ids(assessment.evidence_ids, {e.id for e in items}, "证据评估")
        return {"evidence": [e.model_dump(mode="json") for e in items], "evidence_assessment": assessment.model_dump(mode="json")}

    def world_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        world = ask("world", {"question": question.model_dump(mode="json"), "evidence": evidence_for_model(evidence), "evidence_assessment": state["evidence_assessment"]}, WorldState,
                    "只用证据编号引用事实；不确定的动机必须写为 assumption。若无战略主体，可留空 actors 并说明原因。主体最多 3 个。")
        world.actors = world.actors[:3]
        if len({a.id for a in world.actors}) != len(world.actors):
            raise ValueError("主体 ID 重复")
        if len({a.id for a in world.assumptions}) != len(world.assumptions):
            raise ValueError("假设 ID 重复")
        for content in question.user_assumptions:
            next_number = 1
            existing = {a.id for a in world.assumptions}
            while f"H{next_number:03}" in existing:
                next_number += 1
            from .schemas import Assumption
            world.assumptions.append(Assumption(id=f"H{next_number:03}", created_by="user", content=content, rationale="用户在创建运行时提供"))
        check_ids(world.evidence_refs, {e.id for e in evidence}, "世界状态")
        for actor in world.actors:
            check_ids(actor.visible_evidence_ids, {e.id for e in evidence}, "主体画像")
        valid_parents = {e.id for e in evidence} | {a.id for a in world.assumptions}
        for assumption in world.assumptions:
            check_ids(assumption.parent_ids, valid_parents, "假设")
        return {"world": world.model_dump(mode="json")}

    def simulation_node(state: FlowState):
        world = WorldState.model_validate(state["world"])
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        if not world.actors:
            return {"actions": [], "simulation": []}
        actions, steps = [], []
        current = world.model_dump(mode="json")
        for round_number in (1, 2):
            parent = round_number - 1
            def actor_call(actor):
                visible = evidence_for_model([e for e in evidence if e.id in actor.visible_evidence_ids], 1600)
                action = ask("actor", {"actor": actor.model_dump(), "state": current, "visible_evidence": visible, "round": round_number}, ActorAction,
                             "只代表这个主体做一个可能行动。不可将模拟行动说成真实事实。只引用给你的证据编号。", actor_id=actor.id, round_number=round_number)
                action.id = f"M{round_number}-{actor.id}"
                action.created_by = actor.id
                action.actor_id = actor.id
                action.round = round_number
                action.parent_state = parent
                action.parent_ids = [f"S{parent}"]
                action.kind = "simulation"
                check_ids(action.evidence_ids, {e["id"] for e in visible}, "主体行动")
                check_ids(action.assumption_ids, {a.id for a in world.assumptions}, "主体行动假设")
                return action
            with ThreadPoolExecutor(max_workers=min(3, len(world.actors))) as pool:
                round_actions = list(pool.map(actor_call, world.actors))
            actions.extend(round_actions)
            allowed_variables = set(current.get("variables", {}))
            step_payload = {"state": current, "actions": [a.model_dump(mode="json") for a in round_actions],
                            "round": round_number, "allowed_variable_keys": sorted(allowed_variables)}
            for attempt in range(2):
                step = ask("environment", step_payload, SimulationStep,
                           "联合处理全部行动；保留冲突与条件。状态变化是模拟，不是外部事实。"
                           "state_changes 的键只能从 allowed_variable_keys 中选择，不得新增变量名；"
                           "如需提出新维度，请写在 summary 或 unresolved 中。", round_number=round_number)
                unknown_variables = set(step.state_changes) - allowed_variables
                if not unknown_variables:
                    break
                step_payload["validation_feedback"] = (
                    f"上次输出的 state_changes 含未定义变量 {sorted(unknown_variables)}；"
                    f"请仅使用 {sorted(allowed_variables)} 中的键。")
            else:
                raise ValueError(f"模拟修改了未定义变量：{', '.join(sorted(unknown_variables))}")
            step.id = f"S{round_number}"
            step.parent_ids = [a.id for a in round_actions]
            step.round = round_number
            step.parent_state = parent
            step.next_state = round_number
            step.kind = "simulation"
            check_ids(step.evidence_ids, {e.id for e in evidence}, "环境推进")
            check_ids(step.assumption_ids, {a.id for a in world.assumptions}, "环境推进假设")
            steps.append(step)
            current = {**current, "state_version": round_number, "variables": {**current.get("variables", {}), **step.state_changes}, "simulation_summary": step.summary}
        return {"actions": [a.model_dump(mode="json") for a in actions], "simulation": [s.model_dump(mode="json") for s in steps]}

    def review_node(state: FlowState):
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        world = WorldState.model_validate(state["world"])
        review = ask("review", {"question": state["question"], "evidence": evidence_for_model(evidence), "evidence_assessment": state["evidence_assessment"], "world": state["world"], "actions": state["actions"], "simulation": state["simulation"]}, Review,
                     "检查给定证据节选是否支持关键判断、遗漏反证和模拟跳步。最多列 5 条关键问题，每条简洁；严重问题用 blocked。不要新造证据。")
        if not evidence:
            review.status = "blocked"
            review.issues.append(ReviewIssue(severity="high", claim="证据包为空", explanation="没有可核查的外部证据，不能给概率。"))
        if all(e.source_type == "snippet_only" for e in evidence) and evidence:
            review.issues.append(ReviewIssue(severity="medium", claim="来源仅有搜索片段", explanation="未取得原文，结论需保留限制。"))
        if any(issue.severity == "high" for issue in review.issues) or review.unsupported_claims:
            review.status = "blocked"
        valid = {e.id for e in evidence} | {a.id for a in world.assumptions} | {s["id"] for s in state["simulation"]}
        for issue in review.issues:
            check_ids(issue.affected_ids, valid, "审查意见")
        return {"review": review.model_dump(mode="json")}

    def forecast_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        world = WorldState.model_validate(state["world"])
        review = Review.model_validate(state["review"])
        forecast_payload = {"question": state["question"], "evidence": evidence_for_model(evidence),
                            "evidence_assessment": state["evidence_assessment"], "world": state["world"],
                            "actions": state["actions"], "simulation": state["simulation"], "review": state["review"],
                            "valid_evidence_ids": [e.id for e in evidence],
                            "valid_assumption_ids": [a.id for a in world.assumptions],
                            "valid_simulation_ids": [s["id"] for s in state["simulation"]]}
        for attempt in range(3):
            forecast = ask("forecast", forecast_payload, Forecast,
                           "只用已给资料与审查过的判断。支持/反对的每条主张必须至少引用一个有效证据、假设或模拟编号；"
                           "无法引用的主张请删除。语言简洁。概率是未经校准的主观判断；证据不足或开放问题必须用 null。")
            try:
                validate_forecast(forecast, question, evidence, world,
                                  [SimulationStep.model_validate(x) for x in state["simulation"]], review)
                return {"forecast": forecast.model_dump(mode="json")}
            except ValueError as exc:
                forecast_payload["validation_feedback"] = f"上次报告未通过校验：{exc}。请修正后重新输出完整 JSON。"
        raise ValueError(forecast_payload["validation_feedback"])

    graph = StateGraph(FlowState)
    for name, fn in (("define_question", question_node), ("retrieve", evidence_node), ("model_world", world_node), ("simulate", simulation_node), ("audit", review_node), ("synthesize", forecast_node)):
        graph.add_node(name, fn)
    graph.add_edge(START, start_at)
    graph.add_edge("define_question", "retrieve")
    graph.add_edge("retrieve", "model_world")
    graph.add_edge("model_world", "simulate")
    graph.add_edge("simulate", "audit")
    graph.add_edge("audit", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def execute(record: RunRecord, imported: list[Evidence], store, *, resume: bool = False):
    model = None
    try:
        model = None if record.demo else ModelClient()
        state: FlowState = {"question": record.question.model_dump(mode="json")}
        start_at = "define_question"
        if resume:
            pending = next(((stage, node) for stage, node in STAGE_NODES if stage not in record.stage_outputs), None)
            if pending is None:
                raise ValueError("所有阶段已有快照，无法继续")
            for stage, _ in STAGE_NODES:
                if stage == pending[0]:
                    break
                state.update(record.stage_outputs[stage])
            start_at = pending[1]
            record.retry_history.extend(record.errors)
            record.errors = []
            record.resume_count += 1
            record.finished_at = None
            if model:
                model.usage = record.usage.copy()
        graph = build_graph(record, imported, model, store.directory, start_at=start_at)
        record.status = "running"
        record.stage = next(stage for stage, node in STAGE_NODES if node == start_at)
        store.save(record)
        for update in graph.stream(state, stream_mode="updates"):
            node, output = next(iter(update.items()))
            stage = {"define_question": "question", "retrieve": "evidence", "model_world": "world", "simulate": "simulation", "audit": "review", "synthesize": "forecast"}[node]
            state.update(output)
            record.stage = stage
            record.stage_outputs[stage] = output
            if "question_analysis" in output:
                record.question_analysis = QuestionAnalysis.model_validate(output["question_analysis"])
            if "evidence" in output:
                record.evidence = [Evidence.model_validate(x) for x in output["evidence"]]
                record.evidence_assessment = EvidenceAssessment.model_validate(output["evidence_assessment"])
            if "world" in output:
                record.world = WorldState.model_validate(output["world"])
            if "actions" in output:
                record.actions = [ActorAction.model_validate(x) for x in output["actions"]]
                record.simulation = [SimulationStep.model_validate(x) for x in output["simulation"]]
            if "review" in output:
                record.review = Review.model_validate(output["review"])
            if "forecast" in output:
                record.forecast = Forecast.model_validate(output["forecast"])
            if model:
                record.usage = model.usage.copy()
                record.model = getattr(model, "actual_model", None) or record.model
            store.save(record)
        record.status = record.forecast.status
        record.stage = "done"
    except BudgetExceeded as exc:
        record.status = "partial"
        record.stage = "partial"
        record.errors.append(str(exc))
    except Exception as exc:
        record.status = "failed"
        record.stage = "failed"
        record.errors.append(f"{type(exc).__name__}: {str(exc)[:500]}")
    finally:
        if model:
            record.usage = model.usage.copy()
            record.model = getattr(model, "actual_model", None) or record.model
        record.finished_at = utcnow()
        store.save(record)
