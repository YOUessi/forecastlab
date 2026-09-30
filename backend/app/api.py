from contextlib import asynccontextmanager
from datetime import datetime
from html import escape
from pathlib import Path
from threading import Lock
from uuid import uuid4
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import config
from .demo import DEMO_QUESTION, demo_evidence
from .graph import execute
from .schemas import QuestionDraft, QuestionSpec, RunRecord, RunRequest, Settlement, SettlementRequest, utcnow
from .sources import normalize_import
from .storage import RunStore, VersionConflict
from .question_service import QuestionService, ModelNotConfigured
from .llm import BudgetExceeded
from .schemas import AnalyzeQuestionRequest, ConfirmQuestionRequest


def report_html(run: RunRecord) -> str:
    esc = lambda value: escape(str(value))
    claims = lambda rows: "".join(
        f"<li>{esc(c.text)} <small>{esc(', '.join(c.evidence_ids + c.assumption_ids + c.simulation_ids))}</small></li>" for c in rows
    )
    forecast = run.forecast
    probability = "无有效概率" if not forecast or forecast.probabilities is None else " · ".join(f"{esc(k)} {v:.0%}" for k, v in forecast.probabilities.items())
    lookback_label = (" · 历史回看·非盲测" if any(
        e.source_type == "exercise" and e.retrieved_at > run.question.as_of for e in run.evidence
    ) else "")
    if run.settlement:
        settled = run.settlement
        score = (f"二元 Brier 分数：{settled.brier_score:.4f}（越低越好；单次结果不能证明概率已校准）"
                 if settled.brier_score is not None else "本次预测没有有效概率，无法计算 Brier 分数")
        settlement_html = (f"<p><strong>实际结果：{esc(settled.outcome)}</strong>"
                           f" · {esc(settled.observed_value or '未记录观测值')}</p>"
                           f"<p>{esc(score)}</p>"
                           f"<p>结算来源：<a href='{esc(settled.source_url)}'>{esc(settled.source_title or settled.source_url)}</a>"
                           f" · 记录于 {esc(settled.recorded_at.isoformat())}</p>"
                           + (f"<p>备注：{esc(settled.note)}</p>" if settled.note else ""))
    else:
        settlement_html = "<p>尚未记录实际结果。</p>"
    sources = "".join(
        f"<article id='{esc(e.id)}'><h3>{esc(e.id)} · {esc(e.title)}</h3><p>{esc(e.publisher or '')} · {esc(e.source_type)} · {esc(e.retrieved_at.isoformat())}</p>"
        f"<blockquote>{esc(e.excerpt)}</blockquote>" + (f"<p><a href='{esc(e.source_url)}'>查看来源</a></p>" if e.source_url else "<p>本地/教学材料</p>") + "</article>"
        for e in run.evidence
    )
    return f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>ForecastLab 报告 {esc(run.run_id)}</title>
<style>body{{font:16px/1.7 system-ui,sans-serif;max-width:850px;margin:48px auto;padding:0 24px;color:#183438}}h1,h2{{line-height:1.3}}small{{color:#607578}}article{{border-top:1px solid #d9e5e1;padding:14px 0}}blockquote{{background:#f1f6f4;padding:18px;margin:12px 0}}.tag{{color:#0b776a}}@media print{{a{{color:inherit}}}}</style>
<p class='tag'>FORECASTLAB · {esc('教学演示 / 虚构材料' if run.demo else '运行报告')}{lookback_label}</p><h1>{esc(run.question.question)}</h1>
<p>运行 ID：{esc(run.run_id)} · 状态：{esc(run.status)} · 信息截至：{esc(run.question.as_of.isoformat())} · 结算规则：{esc(run.question.resolution_rule)}</p>
<h2>结论</h2><p>{esc(forecast.conclusion if forecast else '运行未完成')}</p><p><strong>{probability}</strong> · 主观概率，未经校准</p>
<h2>实际结果与评分</h2>{settlement_html}
<h2>支持依据</h2><ul>{claims(forecast.supporting) if forecast else ''}</ul><h2>反对依据</h2><ul>{claims(forecast.opposing) if forecast else ''}</ul>
<h2>模拟与审查</h2><ol>{''.join('<li>'+esc(s.summary)+'</li>' for s in run.simulation)}</ol><p>{esc(', '.join(i.explanation for i in run.review.issues) if run.review else '无审查结果')}</p>
<h2>局限</h2><ul>{''.join('<li>'+esc(v)+'</li>' for v in (forecast.limitations if forecast else run.errors))}</ul><h2>证据原文</h2>{sources}
<footer><small>生成于 {esc(utcnow().isoformat())}；证据来源、假设和模拟记录分开保存。此报告不保证预测正确。</small></footer></html>"""


def create_app(data_dir: Path | None = None, *, question_model_factory=None) -> FastAPI:
    store = RunStore(data_dir or config.DATA_DIR)
    run_lock = Lock()
    settlement_lock = Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.mark_interrupted()
        yield

    app = FastAPI(title="ForecastLab API", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    question_service = QuestionService(store, model_factory=question_model_factory)
    app.state.question_service = question_service

    def question_call(method, *args):
        try:
            return method(*args)
        except ModelNotConfigured as exc:
            raise HTTPException(503, str(exc)) from exc
        except VersionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(429, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/questions/analyze")
    def analyze_question_endpoint(request: AnalyzeQuestionRequest):
        return question_call(question_service.analyze, request)

    @app.get("/api/questions/{draft_id}")
    def get_question_draft(draft_id: str):
        return question_call(question_service.get, draft_id)

    @app.post("/api/questions/{draft_id}/confirm")
    def confirm_question_endpoint(draft_id: str, request: ConfirmQuestionRequest):
        return question_call(question_service.confirm, draft_id, request)


    @app.get("/api/health")
    def health():
        return {"ok": True, "model_configured": bool(config.MODEL_API_KEY), "search_configured": bool(config.TAVILY_API_KEY), "model": config.MODEL_NAME}

    @app.get("/api/examples")
    def examples():
        return {"demo": {"question": DEMO_QUESTION.model_dump(mode="json"), "evidence": [e.model_dump(mode="json") for e in demo_evidence()]},
                "presets": [
                    {"category": "科技", "question": "Python 3.15 是否会在 2026 年 11 月 15 日前发布正式版？", "resolve_by": "2026-11-15T23:59:00Z", "resolution_rule": "以 python.org 正式下载页出现 Python 3.15 正式版本为是，否则为否。", "resolution_source": "https://www.python.org/downloads/"},
                    {"category": "体育", "question": "阿森纳是否会在 2026/27 赛季英超最终排名前四？", "resolve_by": "2027-06-30T23:59:00Z", "resolution_rule": "以英超官网发布的 2026/27 赛季最终积分榜名次 1–4 为是，否则为否。", "resolution_source": "https://www.premierleague.com/tables"},
                    {"category": "公共事件", "question": "NASA Artemis III 是否会在 2027 年 12 月 31 日前完成载人近地轨道飞行测试？", "resolve_by": "2027-12-31T23:59:00Z", "resolution_rule": "以 NASA 官方任务公告确认 Artemis III 载人飞行测试完成为是，否则为否。", "resolution_source": "https://www.nasa.gov/mission/artemis-iii/"},
                ]}

    @app.post("/api/questions/parse")
    def parse_question(draft: QuestionDraft):
        missing = []
        if draft.mode == "binary":
            if not draft.resolve_by:
                missing.append("resolve_by")
            if not draft.resolution_rule.strip():
                missing.append("resolution_rule")
        if missing:
            return {"spec": None, "clarification_fields": missing}
        try:
            spec = QuestionSpec(**draft.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"spec": spec.model_dump(mode="json"), "clarification_fields": []}

    def enqueue(request: RunRequest, background_tasks: BackgroundTasks):
        if not run_lock.acquire(blocking=False):
            raise HTTPException(409, "已有预测正在运行；请等待完成后再提交。")
        try:
            parent = store.get(request.parent_run_id) if request.parent_run_id else None
            if request.parent_run_id and not parent:
                raise HTTPException(404, "父运行不存在")
            if request.evidence_mode == "demo":
                question, evidence = DEMO_QUESTION, demo_evidence()
            else:
                if not config.MODEL_API_KEY:
                    raise HTTPException(503, "未配置 QWEN_API_KEY 或 DEEPSEEK_API_KEY；请先体验教学演示或配置后端密钥。")
                question = request.question
                if request.evidence_mode == "import":
                    evidence = normalize_import(request.evidence, question)
                elif request.evidence_mode == "reuse":
                    if not parent:
                        raise HTTPException(422, "沿用证据需要 parent_run_id")
                    if question.as_of < parent.question.as_of:
                        raise HTTPException(422, "沿用证据时，信息截至时间不能早于父运行")
                    evidence = parent.evidence
                else:
                    if not config.TAVILY_API_KEY:
                        raise HTTPException(503, "未配置 TAVILY_API_KEY；请导入证据包。")
                    evidence = []
            record = RunRecord(run_id=f"run_{uuid4().hex[:12]}", question=question,
                               parent_run_id=request.parent_run_id, question_version=2 if request.parent_run_id else 1,
                               evidence_mode=request.evidence_mode, demo=request.evidence_mode == "demo",
                               model="fixture" if request.evidence_mode == "demo" else config.MODEL_NAME)
            store.save(record)
            def work():
                try:
                    execute(record, evidence, store)
                finally:
                    run_lock.release()
            background_tasks.add_task(work)
            return JSONResponse(status_code=202, content={"run_id": record.run_id, "status": "queued"})
        except ValueError as exc:
            run_lock.release()
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            run_lock.release()
            raise

    @app.post("/api/runs", status_code=202)
    def create_run(request: RunRequest, background_tasks: BackgroundTasks):
        return enqueue(request, background_tasks)

    @app.get("/api/runs")
    def list_runs():
        return [r.model_dump(mode="json") for r in store.list()]

    @app.get("/api/settlements/summary")
    def settlement_summary():
        settled = [r.settlement for r in store.list(1_000_000)
                   if not r.demo and r.question.mode == "binary" and r.settlement is not None]
        scores = [item.brier_score for item in settled if item.brier_score is not None]
        return {"settled_count": len(settled), "scored_count": len(scores),
                "average_brier": round(sum(scores) / len(scores), 6) if scores else None,
                "reference_brier": 0.25}

    def required(run_id: str) -> RunRecord:
        run = store.get(run_id)
        if not run:
            raise HTTPException(404, "运行不存在")
        return run

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume_run(run_id: str, background_tasks: BackgroundTasks):
        if not run_lock.acquire(blocking=False):
            raise HTTPException(409, "已有预测正在运行；请等待完成后再重试。")
        try:
            record = required(run_id)
            if record.status not in {"failed", "partial", "interrupted"}:
                raise HTTPException(409, "只有失败、中断或部分完成的运行可以继续")
            if "forecast" in record.stage_outputs:
                raise HTTPException(409, "该运行已有完整报告")
            if not record.demo and not config.MODEL_API_KEY:
                raise HTTPException(503, "未配置模型密钥")

            def work():
                try:
                    execute(record, record.evidence, store, resume=True)
                finally:
                    run_lock.release()

            background_tasks.add_task(work)
            return JSONResponse(status_code=202, content={"run_id": record.run_id, "status": "queued"})
        except Exception:
            run_lock.release()
            raise

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return required(run_id)

    @app.post("/api/runs/{run_id}/settlement", status_code=201)
    def settle_run(run_id: str, request: SettlementRequest):
        with settlement_lock:
            record = required(run_id)
            if record.demo or record.question.mode != "binary":
                raise HTTPException(422, "仅真实运行的二元预测可以结算")
            if record.settlement is not None:
                raise HTTPException(409, "该运行已记录实际结果")
            if record.question.resolve_by is None or utcnow() < record.question.resolve_by:
                raise HTTPException(409, "结算时间尚未到达")
            if record.forecast is None:
                raise HTTPException(409, "该运行尚无预测报告")
            if request.outcome not in record.question.outcomes:
                raise HTTPException(422, f"实际结果必须是：{'、'.join(record.question.outcomes)}")
            probabilities = record.forecast.probabilities
            score = None
            if probabilities is not None and set(probabilities) == set(record.question.outcomes):
                if all(0 <= value <= 1 for value in probabilities.values()) and abs(sum(probabilities.values()) - 1) <= 0.001:
                    score = round((1 - probabilities[request.outcome]) ** 2, 6)
            record.settlement = Settlement(**request.model_dump(mode="json"),
                                           forecast_probabilities=dict(probabilities) if probabilities is not None else None,
                                           brier_score=score)
            # Keep the original completed-stage snapshot intact; the SQLite record
            # adds the later observed outcome without changing the forecast.
            store.save(record, snapshot=False)
            return record

    @app.get("/api/runs/{run_id}/evidence")
    def get_evidence(run_id: str):
        return required(run_id).evidence

    @app.get("/api/runs/{run_id}/export")
    def export_run(run_id: str, format: str = Query("html", pattern="^(html|json)$")):
        run = required(run_id)
        if format == "json":
            return JSONResponse(run.model_dump(mode="json"), headers={"Content-Disposition": f'attachment; filename="{run.run_id}.json"'})
        return HTMLResponse(report_html(run), headers={"Content-Disposition": f'attachment; filename="{run.run_id}.html"'})

    dist = config.ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "接口不存在")
            return HTMLResponse((dist / "index.html").read_text(encoding="utf-8"))
    return app


app = create_app()
