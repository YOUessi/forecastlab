import json
import re
from copy import deepcopy
from playwright.sync_api import expect

QUESTION = {"question": "青岚项目能否按期发布正式版？", "mode": "scenario", "as_of": "2026-09-30T08:00:00Z",
    "resolve_by": None, "resolution_rule": "", "resolution_source": None, "user_assumptions": []}
FRAME = {"schema_version": 1, "draft_id": "draft_fixture", "revision": 1, "raw_question": QUESTION["question"],
    "proposed_spec": QUESTION, "inputs": [], "clarifications": [], "premises": [{"id": "P001", "content": "测试已完成",
    "origin": "user_explicit", "source_input_id": "I001", "original_span": "测试已完成", "rationale": "需要核查实际范围",
    "user_review": "pending", "treatment": "to_verify", "replaces_id": None}], "alternative_directions": ["还需核查兼容性"],
    "retrieval_plan": [], "status": "ready_for_confirmation", "analysis_record": {"validation_mode": "fixture"}, "demo_case_id": None}
RUN = {"run_id": "run_fixture", "question": {"id": "Q1", "outcomes": ["是","否"], **QUESTION}, "question_origin": "confirmed",
    "question_framing": FRAME, "confirmation_id": "confirm_fixture", "parent_run_id": None, "question_version": 1,
    "evidence_mode": "import", "demo": False, "status": "scenario_only", "stage": "done", "stage_outputs": {},
    "question_analysis": None, "evidence": [], "evidence_assessment": None, "world": None, "actions": [], "simulation": [],
    "review": None, "forecast": None, "settlement": None, "model": "fixture", "started_at": QUESTION["as_of"], "finished_at": QUESTION["as_of"],
    "usage": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}, "errors": []}


def routes(page, *, missing_key=False, runs=None, framing=None, passages=None):
    captured = {"runs": [], "confirmations": [], "analyses": []}
    frame = deepcopy(framing or FRAME)
    def handler(route):
        path = route.request.url.split("/api", 1)[1].split("?", 1)[0]
        method = route.request.method
        status = 200
        if path == "/health":
            data = {"ok": True, "model_configured": not missing_key, "search_configured": True, "model": "fixture"}
        elif path == "/examples": data = {"presets": []}
        elif path == "/settlements/summary": data = {"settled_count": 0, "scored_count": 0, "average_brier": None}
        elif path == "/questions/analyze":
            captured["analyses"].append(route.request.post_data_json)
            data = frame if not missing_key else {"detail": "未配置模型密钥，不能生成真实分析"}
            status = 200 if not missing_key else 503
        elif path.endswith("/confirm"):
            captured["confirmations"].append(route.request.post_data_json)
            data = {"confirmation_id": "confirm_fixture", "framing": frame, "question": RUN["question"], "revision": frame["revision"]}
        elif path == "/questions/draft_fixture": data = {"framing": frame, "confirmation": None}
        elif path == "/runs" and method == "POST":
            captured["runs"].append(route.request.post_data_json)
            data = {"run_id": "run_fixture", "status": "queued"}; status = 202
        elif path == "/runs": data = deepcopy(runs or [])
        elif path.endswith("/passages"): data = passages
        elif path == "/runs/run_fixture": data = deepcopy((runs or [RUN])[0])
        else: data = {"detail": "unknown test route"}; status = 404
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data, ensure_ascii=False))
    page.route("**/api/**", handler)
    return captured


def prepare(page, app_url):
    page.goto(app_url)
    page.get_by_placeholder("例如：某产品能否在 12 月 20 日前发布正式版？").fill(QUESTION["question"])
    page.get_by_role("button", name="开放情景分析").click()
    page.get_by_role("button", name="分析问题", exact=True).click()


def test_question_confirmation_flow(page, app_url):
    captured = routes(page)
    prepare(page, app_url)
    expect(page.get_by_role("button", name="确认并继续", exact=True)).to_be_disabled()
    expect(page.get_by_text("待核查前提，不是已证实事实", exact=True)).to_be_visible()
    page.get_by_label("P001 前提处理").select_option("to_verify")
    page.get_by_role("button", name="确认并继续", exact=True).click()
    expect(page.get_by_text("问题已确认", exact=True)).to_be_visible()
    page.get_by_role("button", name="在线检索", exact=True).click()
    page.get_by_role("button", name=re.compile("^开始预测")).click()
    expect(page.get_by_text("run_fixture", exact=True).first).to_be_visible()
    assert captured["runs"][0]["confirmation_id"] == "confirm_fixture"
    assert "question" not in captured["runs"][0]


def test_edit_invalidates_confirmation(page, app_url):
    routes(page); prepare(page, app_url)
    page.get_by_label("P001 前提处理").select_option("to_verify")
    page.get_by_role("button", name="确认并继续", exact=True).click()
    expect(page.get_by_text("问题已确认", exact=True)).to_be_visible()
    page.get_by_placeholder("例如：某产品能否在 12 月 20 日前发布正式版？").fill("修改了范围，另一个版本能否发布？")
    expect(page.get_by_role("button", name=re.compile("^开始预测"))).to_be_disabled()
    expect(page.get_by_text("内容已修改，请重新分析后确认", exact=True)).to_be_visible()


def test_refresh_loads_saved_draft(page, app_url):
    routes(page)
    page.add_init_script("localStorage.setItem('forecastlab.agent12.draft_id','draft_fixture')")
    page.goto(app_url)
    expect(page.get_by_text("需要核查实际范围", exact=True)).to_be_visible()
    expect(page.get_by_placeholder("例如：某产品能否在 12 月 20 日前发布正式版？")).to_have_value(QUESTION["question"])
    page.reload()
    expect(page.get_by_text("需要核查实际范围", exact=True)).to_be_visible()


def test_missing_key_does_not_create_fake_analysis(page, app_url):
    routes(page, missing_key=True); prepare(page, app_url)
    expect(page.get_by_text("未配置模型密钥，不能生成真实分析", exact=True)).to_be_visible()
    expect(page.get_by_text("需要核查实际范围", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("^开始预测"))).to_be_disabled()
