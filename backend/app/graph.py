"""Explicit SAO workflow. Each node owns a single stage output."""
from concurrent.futures import ThreadPoolExecutor
from math import ceil
import re
import time
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from .schemas import (QuestionSpec, QuestionAnalysis, Evidence, EvidenceAssessment, EvidenceOnlyAudit,
                      WorldState, ActorAction, SimulationStep, Review, ReviewIssue, Forecast,
                      EvidenceOnlyForecast, RunRecord, utcnow)
from .sources import online_search, retrieve_evidence
from .schemas import RetrievalResult, RetrievalLog, Assumption
from .agents.evidence import (assess_evidence, active_framing, make_evidence_context, EvidenceStageError)
from .llm import unique_request_count, request_active_seconds
from .llm import BudgetExceeded, ModelClient
from .demo import demo_output
from . import config


class FlowState(TypedDict, total=False):
    question: dict
    question_analysis: dict
    question_framing: dict
    premise_assumption_map: dict
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


def available_at_cutoff(evidence: Evidence, as_of) -> bool:
    """Allow dated exercise material without pretending it was fetched at the cutoff."""
    if evidence.retrieved_at <= as_of:
        return True
    return (evidence.source_type == "exercise" and evidence.published_at is not None
            and evidence.published_at <= as_of
            and (evidence.updated_at is None or evidence.updated_at <= as_of)
            and (evidence.event_at is None or evidence.event_at <= as_of))


def mistakes_future_outcome_for_missing_evidence(text: str, question: QuestionSpec,
                                                 *, assume_missing: bool = False) -> bool:
    """Catch the common error of demanding observations from the forecast period."""
    if not assume_missing and not re.search(r"缺少|缺失|不足|尚未|未知|无法|不能|没有|未有|未发生|未提供|不具备", text):
        return False
    if re.search(r"未来(?:的)?(?:结果|行情|数据|信息)|预测期|结算(?:日|时|结果)|截至日之后|截止日之后|后续(?:的)?(?:行情|数据|结果)|最终(?:结果|行情)", text):
        return True
    for match in re.finditer(r"(?:(\d{4})\s*[年/-]\s*)?(\d{1,2})\s*[月/-]\s*(?:(\d{1,2})\s*日?)?", text):
        year = int(match.group(1)) if match.group(1) else question.as_of.year
        month = int(match.group(2))
        day = int(match.group(3)) if match.group(3) else None
        if not 1 <= month <= 12:
            continue
        if (year, month) > (question.as_of.year, question.as_of.month):
            return True
        if day is not None and (year, month, day) > (question.as_of.year, question.as_of.month, question.as_of.day):
            return True
    return False


def market_price_context(question: QuestionSpec, evidence: list[Evidence]) -> dict | None:
    """Describe dated price coverage without treating recent momentum as a base rate."""
    if question.mode != "binary" or question.resolve_by is None or not re.search(
        r"指数|股价|股市|股票|A股|ETF|收盘点位|收盘价|期货|汇率", question.question, re.I
    ):
        return None
    horizon_days = max(1, ceil((question.resolve_by - question.as_of).total_seconds() / 86400))
    price_items = [item for item in evidence if re.search(
        r"收盘|收于|涨幅|跌幅|日涨|成交额|振幅|点位|盘中最高|盘中最低", item.excerpt
    ) and item.event_at is not None and item.event_at <= question.as_of]
    return {
        "forecast_horizon_days": horizon_days,
        "dated_price_observation_days": len({item.event_at.date() for item in price_items}),
        "price_source_groups": len({item.source_group for item in price_items}),
        "note": "这些是证据包中明确标注事件日的价格资料数量，不代表完整历史价格序列或经验基准率。",
    }


def trace_for_model(state: FlowState) -> dict:
    """Keep the causal trace and references without repeating verbose agent prose."""
    action_keys = {"id", "actor_id", "round", "action", "evidence_ids", "assumption_ids", "conditions"}
    step_keys = {"id", "round", "summary", "state_changes", "conflicts", "unresolved", "evidence_ids", "assumption_ids"}
    return {
        "actions": [{key: value for key, value in action.items() if key in action_keys} for action in state["actions"]],
        "simulation": [{key: value for key, value in step.items() if key in step_keys} for step in state["simulation"]],
    }


def check_ids(ids: list[str], valid: set[str], label: str):
    missing = set(ids) - valid
    if missing:
        raise ValueError(f"{label}引用不存在：{', '.join(sorted(missing))}")


def canonical_ids(values: list[str], valid: set[str]) -> list[str]:
    """Accept an ID wrapped in explanatory prose, never create a new reference."""
    normalized = []
    for value in values:
        matches = ([value] if value in valid else sorted(
            (item for item in valid if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(item)}(?![A-Za-z0-9_-])", value)),
            key=value.find))
        normalized.extend(matches or [value])
    return list(dict.fromkeys(normalized))


def finding_evidence_map(assessment: dict | None) -> dict[str, list[str]]:
    """Map finding ids (``F001``…) to the evidence ids they cite.

    Review/世界状态 stages routinely reference a finding when they mean the
    evidence behind it. Without this map those references fail validation and the
    whole run aborts, which is what used to happen on more than half of cases.
    """
    mapping: dict[str, list[str]] = {}
    for finding in (assessment or {}).get("findings") or []:
        fid = finding.get("id")
        ids = [c.get("evidence_id") for c in (finding.get("citations") or []) if c.get("evidence_id")]
        if fid and ids:
            mapping[fid] = list(dict.fromkeys(ids))
    return mapping


def resolve_refs(values: list[str], valid: set[str],
                 *, expansions: dict[str, list[str]] | None = None) -> tuple[list[str], list[str]]:
    """Canonicalize model-authored references, expand aliases, drop the rest.

    Model references are advisory: each resolved id is kept, an alias (a finding
    id) is expanded to the ids it stands for, and anything still unknown is
    dropped and reported rather than raising — the surviving output still
    satisfies "no invented ids", and one bad id no longer aborts the run.
    """
    aliases = expansions or {}
    allowed = valid | set(aliases)
    resolved: list[str] = []
    dropped: list[str] = []
    for value in values:
        hits: list[str] = []
        for item in canonical_ids([value], allowed):
            if item in valid:
                hits.append(item)
            else:
                hits.extend(i for i in aliases.get(item, ()) if i in valid)
        if hits:
            resolved.extend(hits)
        else:
            dropped.append(value)
    return list(dict.fromkeys(resolved)), dropped


def canonicalize_forecast_ids(forecast: Forecast, evidence: list[Evidence], world: WorldState,
                              simulation: list[SimulationStep]) -> None:
    evidence_ids = {item.id for item in evidence}
    assumption_ids = {item.id for item in world.assumptions}
    simulation_ids = {item.id for item in simulation}
    for claim in forecast.supporting + forecast.opposing:
        claim.evidence_ids = canonical_ids(claim.evidence_ids, evidence_ids)
        claim.assumption_ids = canonical_ids(claim.assumption_ids, assumption_ids)
        claim.simulation_ids = canonical_ids(claim.simulation_ids, simulation_ids)
    forecast.key_assumptions = canonical_ids(forecast.key_assumptions, assumption_ids)


def validate_forecast(forecast: Forecast, question: QuestionSpec, evidence: list[Evidence], world: WorldState,
                      simulation: list[SimulationStep], review: Review, *, require_probability: bool = False):
    evidence_ids = {e.id for e in evidence}
    assumption_ids = {a.id for a in world.assumptions}
    simulation_ids = {s.id for s in simulation}
    evidence_only = review.probability_basis == "evidence_only"
    for claim in forecast.supporting + forecast.opposing:
        check_ids(claim.evidence_ids, evidence_ids, "报告证据")
        check_ids(claim.assumption_ids, assumption_ids, "报告假设")
        check_ids(claim.simulation_ids, simulation_ids, "报告模拟")
        if not (claim.evidence_ids or claim.assumption_ids or claim.simulation_ids):
            raise ValueError("报告主张没有可展开的依据")
        if evidence_only and (claim.assumption_ids or claim.simulation_ids):
            raise ValueError("仅依据证据的概率不能引用假设或模拟")
    check_ids(forecast.key_assumptions, assumption_ids, "关键假设")
    if evidence_only and forecast.key_assumptions:
        raise ValueError("仅依据证据的概率不能依赖建模假设")
    if question.mode == "scenario" or (review.status == "blocked" and not evidence_only) or not evidence:
        forecast.probabilities = None
        forecast.status = "scenario_only" if question.mode == "scenario" else "insufficient_evidence"
    if require_probability and forecast.probabilities is None:
        raise ValueError("事前证据复审允许主观概率，报告仍未给出概率")
    if forecast.probabilities is not None:
        if set(forecast.probabilities) != set(question.outcomes):
            raise ValueError("概率结果选项与问题不一致")
        if any(p < 0 or p > 1 for p in forecast.probabilities.values()) or abs(sum(forecast.probabilities.values()) - 1) > .001:
            raise ValueError("概率须在 0–1 且合计为 1")
    elif forecast.status == "completed":
        forecast.status = "insufficient_evidence"
    if evidence_only and forecast.probabilities is not None:
        forecast.status = "completed"
        forecast.probability_basis = "evidence_only"


def repair_forecast(forecast: Forecast, question: QuestionSpec, evidence: list[Evidence], world: WorldState,
                    simulation: list[SimulationStep], review: Review, reason: str) -> Forecast:
    """Conservatively retain only traceable claims after model correction fails."""
    evidence_ids = {item.id for item in evidence}
    assumption_ids = {item.id for item in world.assumptions}
    simulation_ids = {item.id for item in simulation}
    removed = 0
    for name in ("supporting", "opposing"):
        valid_claims = []
        for claim in getattr(forecast, name):
            claim.evidence_ids = [item for item in claim.evidence_ids if item in evidence_ids]
            claim.assumption_ids = [item for item in claim.assumption_ids if item in assumption_ids]
            claim.simulation_ids = [item for item in claim.simulation_ids if item in simulation_ids]
            if claim.evidence_ids or claim.assumption_ids or claim.simulation_ids:
                valid_claims.append(claim)
            else:
                removed += 1
        setattr(forecast, name, valid_claims)
    forecast.key_assumptions = [item for item in forecast.key_assumptions if item in assumption_ids]
    forecast.probabilities = None
    forecast.status = ("scenario_only" if question.mode == "scenario" else
                       "insufficient_evidence" if not evidence or (review.status == "blocked" and review.probability_basis != "evidence_only")
                       else "partial")
    forecast.conclusion = "报告生成未通过结构校验，已保存可追溯的依据，但本次未形成概率；请查看下方错误。"
    forecast.limitations.append(f"自动报告的完整性校验未通过（{reason[:160]}），概率已省略。")
    if removed:
        forecast.limitations.append(f"已移除 {removed} 条无法追溯的主张。")
    validate_forecast(forecast, question, evidence, world, simulation, review)
    return forecast


STAGE_NODES = (
    ("question", "define_question"), ("evidence", "retrieve"), ("world", "model_world"),
    ("simulation", "simulate"), ("review", "audit"), ("forecast", "synthesize"),
)


def build_graph(record: RunRecord, imported: list[Evidence], model: ModelClient | None, data_dir, *, start_at: str = "define_question", store=None):
    def ask(role, payload, schema, instructions, *, actor_id=None, round_number=1):
        if record.demo:
            return schema.model_validate(demo_output(role, actor_id, round_number))
        if record.question_framing:
            payload = dict(payload)
            is_evidence_only = role == "evidence_audit" or (role == "forecast" and payload.get("valid_assumption_ids") == [] and "world" not in payload)
            if not is_evidence_only:
                payload["question_framing"] = active_framing(record.question_framing)
            key = "evidence" if "evidence" in payload else "visible_evidence" if "visible_evidence" in payload else None
            if key and record.evidence_assessment:
                ids = {e["id"] for e in payload[key]}
                selected = [e for e in record.evidence if e.id in ids]
                budget = 1600 if role == "world" else 900 if role == "forecast" else 1200
                context = make_evidence_context(selected, record.evidence_assessment, max_chars_per_source=budget)
                payload[key] = context["evidence"]
                payload["evidence_assessment"] = context["assessment"].model_dump(mode="json")
                payload["evidence_context_limitations"] = context["limitations"]
            instructions += " 待核查前提不是事实；F编号只是组织发现，最终引用必须回到E/H/M/S编号，不能引用F或P作为外部证据。"
        return model.complete(role, payload, schema, instructions)

    def question_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        if record.question_framing:
            frame = record.question_framing
            analysis = QuestionAnalysis(normalized_question=question.question,
                search_queries=[t.query for t in frame.retrieval_plan] or [question.question[:400]])
            return {"question_analysis": analysis.model_dump(mode="json"), "question_framing": frame.model_dump(mode="json")}
        if not record.demo and record.evidence_mode in {"import", "reuse"}:
            # Search terms are only consumed by online retrieval; the user has
            # already supplied both the resolved question and the evidence here.
            analysis = QuestionAnalysis(normalized_question=question.question,
                                        search_queries=[question.question[:400]])
            return {"question_analysis": analysis.model_dump(mode="json")}
        analysis = ask("question", {"question": question.model_dump(mode="json")}, QuestionAnalysis,
                       "用户已确认预测目标和结算规则。用一句话规范化问题，给最多 3 个适合寻找原始资料的检索词；不要自行更改日期或结算条件。")
        analysis.search_queries = [q[:400] for q in analysis.search_queries[:3]]
        return {"question_analysis": analysis.model_dump(mode="json")}

    def evidence_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        if record.question_framing:
            retrieval = record.retrieval_result
            if retrieval is None and record.evidence_mode == "online":
                if record.retrieval_started:
                    retrieval = RetrievalResult(status="failed", retrieval_log=[RetrievalLog(task_id=t.id, query=t.query,
                        purpose=t.purpose, status="failed", error="上次取证中断；本运行不重复花费检索额度，请创建新运行")
                        for t in record.question_framing.retrieval_plan])
                else:
                    record.retrieval_started = True
                    if store:
                        store.save(record)
                    retrieval = retrieve_evidence(question, record.question_framing.retrieval_plan, data_dir)
            retrieval = retrieval or RetrievalResult(evidence=[e.model_copy(deep=True) for e in imported])
            record.retrieval_result = retrieval
            if store:
                store.save(record)
            evidence_model = model
            if record.demo:
                from .agent12_demo import EvidenceFixtureModel
                evidence_model = EvidenceFixtureModel()
            assessment = assess_evidence(question, record.question_framing, retrieval, evidence_model, data_dir)
            record.evidence, record.evidence_assessment = retrieval.evidence, assessment
            return {"evidence": [e.model_dump(mode="json") for e in retrieval.evidence],
                    "evidence_assessment": assessment.model_dump(mode="json")}
        if record.evidence_mode == "online":
            queries = QuestionAnalysis.model_validate(state["question_analysis"]).search_queries
            items = online_search(question, data_dir, queries)
        else:
            items = imported
        assessment = ask("evidence", {"question": state["question"], "evidence": evidence_for_model(items)}, EvidenceAssessment,
                         "归纳资料冲突和缺口，只引用实际存在的证据编号。搜索摘要不是全文证据；不可编造新来源。"
                         "缺口只列信息截至时间当时可能取得却未提供的资料；未来结算结果尚未发生是预测对象，不是证据缺口。")
        assessment.evidence_ids, dropped_refs = resolve_refs(assessment.evidence_ids, {e.id for e in items})
        if dropped_refs:
            record.errors.append(f"证据评估丢弃无法解析的引用：{', '.join(dropped_refs)}")
        assessment.gaps = [gap for gap in assessment.gaps
                           if not mistakes_future_outcome_for_missing_evidence(gap, question, assume_missing=True)]
        if mistakes_future_outcome_for_missing_evidence(assessment.summary, question):
            assessment.summary = (f"已整理 {len(items)} 条截至信息日的资料；预测期结果尚未发生，"
                                  "应通过有保留的概率表达不确定性。")
        return {"evidence": [e.model_dump(mode="json") for e in items], "evidence_assessment": assessment.model_dump(mode="json")}

    def world_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        world = ask("world", {"question": question.model_dump(mode="json"), "evidence": evidence_for_model(evidence, 1600), "evidence_assessment": state["evidence_assessment"]}, WorldState,
                    "只用证据编号引用事实；不确定的动机必须写为 assumption。若无战略主体，可留空 actors 并说明原因。主体最多 3 个。"
                    "信息截至时间之后的事件均未发生，计划发布日期不能写成实际发布日期。"
                    "市场价格问题可以没有战略主体；预测期行情未知是需要预测的目标，不能据此认定无法预测。")
        world.actors = world.actors[:3]
        if len({a.id for a in world.actors}) != len(world.actors):
            raise ValueError("主体 ID 重复")
        if len({a.id for a in world.assumptions}) != len(world.assumptions):
            raise ValueError("假设 ID 重复")
        allowed_conditions = set(question.user_assumptions)
        if record.question_framing:
            allowed_conditions |= {p.content for p in record.question_framing.premises
                if p.user_review == "retained" and p.treatment == "scenario_condition"}
            for a in world.assumptions:
                if a.created_by == "user" and a.content not in allowed_conditions:
                    a.created_by = "model"
                    a.rationale = "模型提出，未经用户指定为情景条件；" + a.rationale
        mapping = {}
        conditions = [(None, text) for text in question.user_assumptions]
        if record.question_framing:
            conditions += [(p.id, p.content) for p in record.question_framing.premises
                           if p.user_review == "retained" and p.treatment == "scenario_condition"]
        for premise_id, content in conditions:
            assumption = next((a for a in world.assumptions if a.content == content), None)
            if assumption is None:
                existing = {a.id for a in world.assumptions}
                number = 1
                while f"H{number:03}" in existing:
                    number += 1
                assumption = Assumption(id=f"H{number:03}", created_by="user", content=content,
                    rationale="用户明确指定的情景条件，不是已证实事实")
                world.assumptions.append(assumption)
            assumption.created_by = "user"
            if premise_id:
                mapping[premise_id] = assumption.id
        record.premise_assumption_map = mapping
        evidence_ids = {e.id for e in evidence}
        findings = finding_evidence_map(state.get("evidence_assessment"))
        world.evidence_refs, dropped_refs = resolve_refs(world.evidence_refs, evidence_ids, expansions=findings)
        for actor in world.actors:
            actor.visible_evidence_ids, dropped = resolve_refs(actor.visible_evidence_ids, evidence_ids, expansions=findings)
            dropped_refs += dropped
        valid_parents = evidence_ids | {a.id for a in world.assumptions}
        for assumption in world.assumptions:
            assumption.parent_ids, dropped = resolve_refs(assumption.parent_ids, valid_parents, expansions=findings)
            dropped_refs += dropped
        if dropped_refs:
            record.errors.append(f"世界状态丢弃无法解析的引用：{', '.join(dict.fromkeys(dropped_refs))}")
        return {"world": world.model_dump(mode="json"), "premise_assumption_map": mapping}

    def simulation_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        world = WorldState.model_validate(state["world"])
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        if not world.actors:
            return {"actions": [], "simulation": []}
        actions, steps = [], []
        current = world.model_dump(mode="json")
        for round_number in (1, 2):
            parent = round_number - 1
            def actor_call(actor):
                visible = evidence_for_model([e for e in evidence if e.id in actor.visible_evidence_ids], 1000)
                action = ask("actor", {"question": state["question"], "actor": actor.model_dump(), "state": current, "visible_evidence": visible, "round": round_number}, ActorAction,
                             "只代表这个主体做一个可能行动。信息截至时间之后的行动只能是假设情景，不可说成真实事实；计划日期不是实际发布日期。只引用给你的证据编号。", actor_id=actor.id, round_number=round_number)
                action.id = f"M{round_number}-{actor.id}"
                action.created_by = actor.id
                action.actor_id = actor.id
                action.round = round_number
                action.parent_state = parent
                action.parent_ids = [f"S{parent}"]
                action.kind = "simulation"
                action.evidence_ids, _ = resolve_refs(action.evidence_ids, {e["id"] for e in visible})
                action.assumption_ids, _ = resolve_refs(action.assumption_ids, {a.id for a in world.assumptions})
                return action
            with ThreadPoolExecutor(max_workers=min(3, len(world.actors))) as pool:
                round_actions = list(pool.map(actor_call, world.actors))
            actions.extend(round_actions)
            allowed_variables = set(current.get("variables", {}))
            step_payload = {"question": state["question"], "state": current, "actions": [a.model_dump(mode="json") for a in round_actions],
                            "round": round_number, "allowed_variable_keys": sorted(allowed_variables)}
            step = ask("environment", step_payload, SimulationStep,
                       f"联合处理全部行动；保留冲突与条件。当前信息截至时间为 {question.as_of.isoformat()}。"
                       "此后状态只能用‘若...则...’的条件式描述，绝不能把计划或模拟结果写成已发生的历史事实。"
                       "state_changes 的键只能从 allowed_variable_keys 中选择，不得新增变量名；"
                       "如需提出新维度，请写在 summary 或 unresolved 中。", round_number=round_number)
            unknown_variables = set(step.state_changes) - allowed_variables
            if unknown_variables:
                step.state_changes = {key: value for key, value in step.state_changes.items() if key in allowed_variables}
                step.unresolved.append(f"模型提出未定义变量 {', '.join(sorted(unknown_variables))}；未写入状态。")
            step.id = f"S{round_number}"
            step.parent_ids = [a.id for a in round_actions]
            step.round = round_number
            step.parent_state = parent
            step.next_state = round_number
            step.kind = "simulation"
            step.evidence_ids, _ = resolve_refs(step.evidence_ids, {e.id for e in evidence},
                                                expansions=finding_evidence_map(state.get("evidence_assessment")))
            step.assumption_ids, _ = resolve_refs(step.assumption_ids, {a.id for a in world.assumptions})
            steps.append(step)
            current = {**current, "state_version": round_number, "variables": {**current.get("variables", {}), **step.state_changes}, "simulation_summary": step.summary}
        return {"actions": [a.model_dump(mode="json") for a in actions], "simulation": [s.model_dump(mode="json") for s in steps]}

    def review_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        world = WorldState.model_validate(state["world"])
        review = ask("review", {"question": state["question"], "evidence": evidence_for_model(evidence, 1200), "evidence_assessment": state["evidence_assessment"], "world": state["world"], **trace_for_model(state)}, Review,
                     "检查给定证据节选是否支持关键判断、遗漏反证和模拟跳步。最多列 5 条关键问题，每条不超过 80 字；严重问题用 blocked。"
                     "信息截至日之后的结果未知是预测对象，不得要求未来证据来证明结果；可指出截至日当时缺少的资料。"
                     "affected_ids 可引用已有证据、假设、主体、行动或模拟编号，不能新造编号或证据。")
        future_gap_found = any(mistakes_future_outcome_for_missing_evidence(
            f"{issue.claim} {issue.explanation}", question) for issue in review.issues)
        future_gap_found |= any(mistakes_future_outcome_for_missing_evidence(x, question, assume_missing=True)
                                for x in review.missing_evidence)
        future_gap_found |= any(mistakes_future_outcome_for_missing_evidence(x, question)
                                for x in review.unsupported_claims)
        future_gap_found |= mistakes_future_outcome_for_missing_evidence(world.summary, question)
        review.issues = [issue for issue in review.issues if not mistakes_future_outcome_for_missing_evidence(
            f"{issue.claim} {issue.explanation}", question)]
        review.missing_evidence = [x for x in review.missing_evidence
                                   if not mistakes_future_outcome_for_missing_evidence(x, question, assume_missing=True)]
        review.unsupported_claims = [x for x in review.unsupported_claims
                                     if not mistakes_future_outcome_for_missing_evidence(x, question)]
        if future_gap_found:
            review.issues.append(ReviewIssue(
                severity="medium", claim="预测期结果未知应由概率表达",
                explanation="审查排除了要求未来行情的判断；概率仅使用截至日证据。"))
        if not evidence:
            review.status = "blocked"
            review.issues.append(ReviewIssue(severity="high", claim="证据包为空", explanation="没有可核查的外部证据，不能给概率。"))
        if all(e.source_type == "snippet_only" for e in evidence) and evidence:
            review.issues.append(ReviewIssue(severity="medium", claim="来源仅有搜索片段", explanation="未取得原文，结论需保留限制。"))
        # A forecast-period claim can never be proven at the as-of date, so a non-empty
        # unsupported_claims list is normal rather than a blocking defect. Record it as a
        # medium issue and let only genuine high-severity findings block the probability.
        for claim in review.unsupported_claims:
            review.issues.append(ReviewIssue(severity="medium", claim="未能事前举证的主张",
                                             explanation=claim[:200]))
        if any(issue.severity == "high" for issue in review.issues):
            review.status = "blocked"
        elif future_gap_found and review.status == "blocked":
            review.status = "qualified"
        valid = ({e.id for e in evidence} | {a.id for a in world.assumptions} | {a.id for a in world.actors}
                 | {a["id"] for a in state["actions"]} | {s["id"] for s in state["simulation"]})
        findings = finding_evidence_map(state.get("evidence_assessment"))
        dropped_refs: list[str] = []
        for issue in review.issues:
            issue.affected_ids, dropped = resolve_refs(issue.affected_ids, valid, expansions=findings)
            dropped_refs += dropped
        if dropped_refs:
            record.errors.append(f"审查意见丢弃无法解析的引用：{', '.join(dict.fromkeys(dropped_refs))}")
        review.probability_basis = "full" if review.status != "blocked" else "none"
        if (review.status == "blocked" or future_gap_found) and question.mode == "binary" and evidence:
            audit = ask("evidence_audit", {"question": state["question"], "evidence": evidence_for_model(evidence, 1200),
                                           "evidence_assessment": state["evidence_assessment"]}, EvidenceOnlyAudit,
                        "仅审查信息截至日已有的外部证据，不使用世界状态、假设、主体行动或模拟结果。"
                        "source_type=exercise 表示用户事后整理的历史练习资料，不代表内容虚构；须有截至日前的发布日期，"
                        "但不是当时冻结的盲回测，应提示回看偏差。"
                        "判断是否足以给一个有保留、未经校准的主观概率。未来结果尚未发生、资料仅有一两个来源或存在延期风险，"
                        "都不是自动阻断理由，应通过不确定的概率表达；若证据本身为空、晚于截至日、无法核查或不支持问题，才设 can_estimate=false。")
            if audit.can_estimate and all(available_at_cutoff(e, question.as_of) for e in evidence):
                review.probability_basis = "evidence_only"
            elif future_gap_found:
                review.status = "blocked"
                review.probability_basis = "none"
        return {"review": review.model_dump(mode="json")}

    def forecast_node(state: FlowState):
        question = QuestionSpec.model_validate(state["question"])
        evidence = [Evidence.model_validate(x) for x in state["evidence"]]
        world = WorldState.model_validate(state["world"])
        review = Review.model_validate(state["review"])
        evidence_only = review.probability_basis == "evidence_only"
        price_context = market_price_context(question, evidence)
        # The full-basis payload is built even on the evidence-only path, so the same
        # run can also produce a shadow forecast that *does* use world + simulation.
        # That gives a paired comparison on identical question/evidence.
        full_world = world
        full_simulation = [SimulationStep.model_validate(x) for x in state["simulation"]]
        full_payload = {"question": state["question"], "evidence": evidence_for_model(evidence, 900),
                        "evidence_assessment": state["evidence_assessment"], "world": state["world"],
                        **trace_for_model(state), "review": state["review"],
                        "valid_evidence_ids": [e.id for e in evidence],
                        "valid_assumption_ids": [a.id for a in full_world.assumptions],
                        "valid_simulation_ids": [s["id"] for s in state["simulation"]]}
        full_instructions = "只用已给资料与审查过的判断。支持/反对的每条主张必须至少引用一个有效证据、假设或模拟编号；无法引用的主张请删除。"
        full_probability_instructions = (f"概率键必须严格为 {question.outcomes}，数值在 0 到 1 且合计为 1；"
                                        "概率是未经校准的主观判断；证据不足或开放问题必须用 null。")
        if evidence_only:
            world = WorldState(summary="仅使用事前外部证据")
            simulation = []
            forecast_payload = {"question": state["question"], "evidence": evidence_for_model(evidence, 900),
                                "valid_evidence_ids": [e.id for e in evidence],
                                "valid_assumption_ids": [], "valid_simulation_ids": []}
            instructions = ("这是二元事件的事前预测，必须给出非 null 的是/否主观概率。"
                            "仅使用给定的截至日外部证据，完全忽略世界建模、审查推断、模拟和未经核实的假设；"
                            "支持与反对的每条主张只能引用有效的 E 编号。"
                            "预测期结果尚未发生是预测目标，不能要求它作为事前证据。"
                            "证据有限时把不确定性体现在接近中性的概率中，并说明来源和回看偏差；不得假装概率已校准。")
            probability_instructions = (f"概率键必须严格为 {question.outcomes}，数值在 0 到 1 且合计为 1，"
                                        "probabilities 不能为 null。")
            forecast_schema = EvidenceOnlyForecast
        else:
            simulation = full_simulation
            forecast_payload = full_payload
            instructions = full_instructions
            probability_instructions = full_probability_instructions
            forecast_schema = Forecast
        if price_context:
            forecast_payload["market_price_context"] = price_context
            full_payload["market_price_context"] = price_context
            price_note = ("对于市场价格问题，先比较预测期限与历史价格覆盖：一两日涨势不能直接外推到月末，"
                          "高振幅也可能意味着回撤；宏观指标与指数涨跌之间不能直接画等号。"
                          "没有查到利空消息不是上涨证据。若缺少同期限历史基准率、波动和估值资料，"
                          "不要把微弱证据表达成明显的方向优势；在局限中指出缺少哪些事前资料。"
                          "历史练习绝不可使用信息截至日之后的实际结果。")
            instructions += price_note
            full_instructions += price_note
        for attempt in range(2):
            forecast = ask("forecast", forecast_payload, forecast_schema,
                           instructions + "语言简洁。" + probability_instructions)
            forecast.probability_basis = "evidence_only" if evidence_only else "full"
            canonicalize_forecast_ids(forecast, evidence, world, simulation)
            if evidence_only:
                # The evidence-only report cannot acquire new model assumptions.
                # Keep evidence-backed prose, but remove references to the excluded branch.
                forecast.key_assumptions = []
                for claim in forecast.supporting + forecast.opposing:
                    claim.assumption_ids = []
                    claim.simulation_ids = []
                forecast.supporting = [claim for claim in forecast.supporting if claim.evidence_ids]
                forecast.opposing = [claim for claim in forecast.opposing if claim.evidence_ids]
                forecast.limitations = [item for item in forecast.limitations
                                        if not mistakes_future_outcome_for_missing_evidence(item, question)]
            try:
                validate_forecast(forecast, question, evidence, world, simulation, review,
                                  require_probability=evidence_only)
                if evidence_only:
                    forecast.limitations.append("概率仅依据截至日已有证据，未采用模拟行动或建模假设。")
                if evidence_only and config.SHADOW_FULL:
                    # Shadow forecast: the same question and evidence, judged with the world
                    # state and simulation allowed. A failed shadow is recorded, never raised,
                    # so it cannot break the scored run.
                    shadow_review = review.model_copy(update={"status": "passed", "probability_basis": "full"})
                    try:
                        shadow = ask("forecast", full_payload, Forecast,
                                     full_instructions + "语言简洁。" + full_probability_instructions)
                        shadow.probability_basis = "full"
                        canonicalize_forecast_ids(shadow, evidence, full_world, full_simulation)
                        # Drop anything still unresolvable so one stray id cannot void the
                        # shadow, and keep only claims that retain a traceable reference.
                        ev_ids = {e.id for e in evidence}
                        as_ids = {a.id for a in full_world.assumptions}
                        si_ids = {s.id for s in full_simulation}
                        shadow.key_assumptions = [i for i in shadow.key_assumptions if i in as_ids]
                        for claim in shadow.supporting + shadow.opposing:
                            claim.evidence_ids = [i for i in claim.evidence_ids if i in ev_ids]
                            claim.assumption_ids = [i for i in claim.assumption_ids if i in as_ids]
                            claim.simulation_ids = [i for i in claim.simulation_ids if i in si_ids]
                        shadow.supporting = [c for c in shadow.supporting
                                             if c.evidence_ids or c.assumption_ids or c.simulation_ids]
                        shadow.opposing = [c for c in shadow.opposing
                                           if c.evidence_ids or c.assumption_ids or c.simulation_ids]
                        validate_forecast(shadow, question, evidence, full_world, full_simulation, shadow_review)
                        record.shadow_forecast = shadow
                    except (ValueError, RuntimeError) as exc:
                        try:
                            shadow = repair_forecast(shadow, question, evidence, full_world, full_simulation,
                                                     shadow_review, str(exc))
                            record.shadow_forecast = shadow
                            record.errors.append(f"影子 full 预测经兜底修复：{str(exc)[:120]}")
                        except (ValueError, RuntimeError) as inner:
                            record.errors.append(f"影子 full 预测失败：{str(inner)[:200]}")
                if (price_context and price_context["forecast_horizon_days"] >= 14
                        and price_context["dated_price_observation_days"] <= 3):
                    forecast.limitations.append(
                        f"证据包中明确标注事件日的价格资料只有 {price_context['dated_price_observation_days']} 个交易日，"
                        f"预测跨度约 {price_context['forecast_horizon_days']} 天；未据此验证同期限历史基准率或波动分布。")
                if any(e.source_type == "exercise" and e.retrieved_at > question.as_of for e in evidence):
                    forecast.limitations.append("历史演练资料是事后按发布日期整理，并非截至日冻结快照；可能存在回看偏差。")
                return {"forecast": forecast.model_dump(mode="json")}
            except ValueError as exc:
                forecast_payload["validation_feedback"] = f"上次报告未通过校验：{exc}。请修正后重新输出完整 JSON。"
        forecast = repair_forecast(forecast, question, evidence, world, simulation, review,
                                   forecast_payload["validation_feedback"])
        if any(e.source_type == "exercise" and e.retrieved_at > question.as_of for e in evidence):
            forecast.limitations.append("历史演练资料是事后按发布日期整理，并非截至日冻结快照；可能存在回看偏差。")
        return {"forecast": forecast.model_dump(mode="json")}

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
    stage_names = [stage for stage, _ in STAGE_NODES]
    current_stage = stage_names[0]
    stage_started = time.monotonic()
    try:
        if record.demo:
            model = None
        elif record.question_framing:
            previous_calls = store.list_calls(record.run_id)
            prior_usage = {"calls": max(len(previous_calls), record.usage["calls"]),
                "prompt_tokens": max(sum(c.prompt_tokens for c in previous_calls), record.usage["prompt_tokens"]),
                "completion_tokens": max(sum(c.completion_tokens for c in previous_calls), record.usage["completion_tokens"])}
            cap = max(0, config.MAX_CALLS - unique_request_count(record.preparation_records))
            prep_seconds = sum(c.elapsed_seconds for c in record.preparation_records)
            retrieval_seconds = max((log.elapsed_seconds for log in record.retrieval_result.retrieval_log), default=0) if record.retrieval_result else 0
            measured_runtime = request_active_seconds(previous_calls) + retrieval_seconds
            model = ModelClient(initial_usage=prior_usage,
                initial_active_seconds=prep_seconds + max(record.active_seconds, measured_runtime),
                call_limit=cap, on_reserve=lambda h, v: store.reserve_call(record.run_id, "runtime", call_limit=cap,
                    input_hash=h, prompt_version=v), on_finish=store.finish_call)
        else:
            model = ModelClient()
        state: FlowState = {"question": record.question.model_dump(mode="json")}
        if record.question_framing:
            state["question_framing"] = record.question_framing.model_dump(mode="json")
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
            current_stage = pending[0]
            record.retry_history.extend(record.errors)
            record.errors = []
            record.resume_count += 1
            record.finished_at = None
            if model and not record.question_framing:
                model.usage = record.usage.copy()
        graph = build_graph(record, imported, model, store.directory, start_at=start_at, store=store)
        record.status = "running"
        record.stage = current_stage
        record.failed_stage = None
        store.save(record)
        stage_started = time.monotonic()
        for update in graph.stream(state, stream_mode="updates"):
            node, output = next(iter(update.items()))
            stage = {"define_question": "question", "retrieve": "evidence", "model_world": "world", "simulate": "simulation", "audit": "review", "synthesize": "forecast"}[node]
            record.stage_durations[stage] = round(time.monotonic() - stage_started, 3)
            state.update(output)
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
                if record.question_framing and hasattr(model, "active_seconds"):
                    record.active_seconds = max(record.active_seconds, model.active_seconds-sum(c.elapsed_seconds for c in record.preparation_records))
            next_index = stage_names.index(stage) + 1
            current_stage = stage_names[next_index] if next_index < len(stage_names) else "done"
            record.stage = current_stage
            store.save(record)
            stage_started = time.monotonic()
        record.status = record.forecast.status
        record.stage = "done"
    except EvidenceStageError as exc:
        record.evidence = exc.result.evidence
        record.retrieval_result = exc.result
        record.evidence_assessment = exc.assessment
        record.status = "failed"
        record.stage = "failed"
        record.failed_stage = current_stage
        record.errors.append(str(exc))
    except BudgetExceeded as exc:
        record.status = "partial"
        record.stage = "partial"
        record.failed_stage = current_stage
        record.stage_durations[current_stage] = round(time.monotonic() - stage_started, 3)
        record.errors.append(str(exc))
    except Exception as exc:
        record.status = "failed"
        record.stage = "failed"
        record.failed_stage = current_stage
        record.stage_durations[current_stage] = round(time.monotonic() - stage_started, 3)
        record.errors.append(f"{type(exc).__name__}: {str(exc)[:500]}")
    finally:
        if model:
            record.usage = model.usage.copy()
            record.model = getattr(model, "actual_model", None) or record.model
        if record.question_framing:
            record.model_calls = store.list_calls(record.run_id)
            if model and hasattr(model, "active_seconds"):
                record.active_seconds = max(0, model.active_seconds - sum(c.elapsed_seconds for c in record.preparation_records))
        record.finished_at = utcnow()
        store.save(record)
