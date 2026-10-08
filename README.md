# ForecastLab

基于问题确认、证据溯源与多主体情景推演的研究工作台。真实数据、模型假设和模拟结果分别留存；开放问题使用情景分析，概率保持 `null`。二元预测的概率是未经校准的主观判断。

当前界面保留树状推演画布，新建研究从空白问题开始。不会自动载入示例或离线演练记录。真实分析需要后端模型服务，联网取证另需 Brave（优先）或 Tavily。

## 启动

环境：Python 3.12、uv、Node.js 20.19+/22.12+、npm。

```bash
uv sync --locked --group browser
npm --prefix frontend ci
npm --prefix frontend run build
cp .env.example .env
# 在后端 .env 配置模型和搜索服务，勿写入前端或提交凭据。
uv run uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。开发前端可执行 `npm --prefix frontend run dev`，Vite 将 `/api` 转发到8000。缺少模型或搜索配置时返回明确错误，不以固定答案替代真实调用。

配置采用 OpenAI 兼容接口：`QWEN_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL`，兼容原 `DEEPSEEK_*` 设置；两者同时存在时优先 Qwen。搜索配置为 `BRAVE_SEARCH_API_KEY` 或 `TAVILY_API_KEY`。同一应用进程一次接受一个运行，失败后可通过页面或 resume API 从首个未完成阶段继续。

通用容器部署可以使用 `docker compose up -d --build`，数据保存在宿主机 `data/`。Group8 服务器使用独立用户进程和本地 GPU 模型，必须遵守物理4–7限制；详见 [服务器部署](docs/server-deployment.md)。

## 验证

```bash
uv run pytest -q
npm --prefix frontend run build
uv run --group browser python -m playwright install chromium
uv run --group browser pytest frontend/tests -q
```

浏览器回归仅访问临时本机服务，覆盖真实后端固定测试与模拟响应；教学样例不代表预测质量。Windows 可通过 `FORECASTLAB_BROWSER_EXECUTABLE` 指定已安装的 Chromium。源码打包脚本只从已提交版本导出，排除 `.env`、数据库和运行资料。

Agent 1–2 的接口与契约说明仍见 [实现记录](docs/agent12/implementation-report.md)、[API](docs/agent12/api.md) 和 [局限](docs/agent12/limitations.md)；其中早期教学入口截图不代表当前工作台布局。

## 结果结算与评分

二元预测的结算时间到达后，可在“结果与历史”中录入实际结果、可核查来源和观测值。系统保留原概率，另存结算记录，并计算二元 Brier 分数 `(P(是) - 实际是的取值)^2`；越低越好。没有有效概率的运行仍可记录结果，但不纳入评分。页面会展示已结算数量和平均分；少量案例的平均分不能证明概率已校准。

市场价格预测会提示模型核对预测跨度与证据包中有日期的价格资料覆盖，避免把一两天涨势直接外推到月末。历史练习资料如在预测截点之后才取回，会标记“历史回看·非盲测”。一次结果不应用来回写事前概率；完整案例见[科创 50 历史预测回看](docs/market-postmortem-2026-07.md)。

导入证据包是 JSON 数组，或包含 `evidence` 数组的对象。最小条目：

```json
[
  {
    "title": "来源标题",
    "source_url": "https://example.org/actual-source",
    "publisher": "发布方",
    "published_at": "2026-09-01T00:00:00Z",
    "excerpt": "从原始来源保存的支持判断的原文片段。"
  }
]
```

把示例网址和内容替换为真实来源。后端会分配 `E001...` 编号、抓取/导入时间和 SHA-256 内容哈希。严格盲回测需要在预测截点前冻结的证据快照；事后找到、可证明发表于截点前的资料只能标为 `source_type: "exercise"`，属于有回看偏差风险的历史练习。若来源只有搜索摘要，请在导入材料中明确注明；在线 Tavily 返回没有正文时会自动标为 `snippet_only`。

思考模式默认关闭，可用 `FORECASTLAB_ENABLE_THINKING=true` 启用 Qwen 的思考参数。思考会占用输出预算，需要同时配置足够的 `FORECASTLAB_MAX_OUTPUT_TOKENS`、请求时限与上下文容量；结构和来源校验继续执行。实际可用模型以对应服务提供方的模型列表为准。`QWEN_MODEL` 可切换模型。首次接入应使用少量问题确认账户权限、模型参数和账单。运行上限由 `.env` 中的 `FORECASTLAB_MAX_CALLS`（默认 18）与 `FORECASTLAB_MAX_SECONDS`（默认 300）控制。运行详情会记录各阶段耗时；失败时显示中断阶段和原因，可从该阶段继续。

## 工作流与边界

```text
QuestionSpec → QuestionAnalysis → Evidence[] + EvidenceAssessment
             → WorldState + ActorProfile[]
             → {ActorAction × 3} → SimulationStep S1
             → {ActorAction × 3} → SimulationStep S2
             → Review → Forecast
```

- 模型只生成结构化判断候选；URL、证据编号、内容哈希和运行状态由代码管理。模型读取长度受控的证据节选，完整检索内容保存在本地快照中。
- 同一轮的主体读取同一个父状态；环境在收齐行动后统一推进。模拟结果保持 `M/S` 身份，不会变成 `E` 类外部证据。
- 代码核对引用 ID、时间截点、父状态和概率；审查 Agent 核对内容支持度。证据不足或审查阻断时不输出概率。
- 所有角色共用同一个已配置模型，不等于独立专家；概率是主观判断，未经校准。
- 在线检索优先由 Brave 提供，兼容 Tavily，模型本身不承担互联网搜索。没有账号系统、断点自动续算和全网持续监控；自托管 GPU 部署见部署说明。

## API

启动后访问 `/docs` 查看 OpenAPI。主要接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/questions/analyze` | Agent 1 分析问题、提出澄清、识别候选前提 |
| GET | `/api/questions/{draft_id}` | 读取问题草稿、版本和确认记录 |
| POST | `/api/questions/{draft_id}/confirm` | 保存用户对候选前提的逐项决定 |
| POST | `/api/questions/parse` | 旧版/兼容字段检查接口 |
| POST | `/api/runs` | 通过 `confirmation_id` 创建新版运行，或兼容旧版直接输入 |
| POST | `/api/runs/{id}/resume` | 从失败、中断或部分完成运行的首个未完成阶段继续 |
| GET | `/api/runs` | 历史列表 |
| GET | `/api/runs/{id}` | 阶段、运行记录与结果 |
| GET | `/api/runs/{id}/evidence` | 来源详情 |
| GET | `/api/runs/{id}/evidence-assessment` | Agent 2 的逐项发现、冲突、缺口和检索日志 |
| GET | `/api/runs/{id}/evidence/{evidence_id}/passages` | 查看登记快照中的原文段落和引用位置 |
| POST | `/api/runs/{id}/settlement` | 截止后记录实际结果与来源，计算二元 Brier |
| GET | `/api/settlements/summary` | 已结算数量与平均评分 |
| GET | `/api/runs/{id}/export?format=html\|json` | 导出报告或原始记录 |
| GET | `/api/health` | 密钥配置状态，不返回密钥 |

`POST /api/runs` 的请求体包含 `question`（`QuestionSpec`）、`evidence_mode`（`import` / `online` / `reuse` / `demo`）、`evidence`（导入时必填）和可选 `parent_run_id`。`reuse` 必须提供父运行 ID，后端沿用已保存的证据快照；修改条件后重新提交会产生新 ID，历史记录不被覆盖。

## 测试与评估

```bash
uv run pytest -q
cd frontend && npm run build
```

测试覆盖完整演示、引用与概率约束、时间截点、服务重启标记，以及 HTML 导出转义。`examples/classroom-demo.json` 是**教学虚构情境**，不能用于真实预测质量评估。

实际实验应先冻结问题、提示词、模型、证据包和预算。`eval/baseline.py` 用**同一问题与证据包**做一次单 Agent 模型调用：

```bash
uv run python eval/baseline.py path/to/frozen-pack.json --output baseline.json
```

结算后的结果表使用 `[{"id":"Q1","category":"tech","outcome":1,"full_p":0.6,"baseline_p":0.5}]` 格式，缺失概率填 `null`。评分脚本同时输出成功覆盖率、成功样本 Brier 与将拒答按 0.5 回退的全样本 Brier：

```bash
uv run python eval/score.py path/to/settled-results.json
```

请保留失败/拒答、引用人工抽查、耗时与 token 记录；历史问题要说明模型可能记住答案。仓库不附带虚构的实验得分。

## 目录

```text
backend/app/       数据契约、证据入口、兼容接口适配、状态图、API、SQLite
backend/tests/     契约与端到端测试
frontend/src/      React 树状推演画布与研究阅读区
examples/          教学演示数据
eval/              单 Agent 基线与 Brier/覆盖率脚本
docs/              原始工程计划与课程交付模板
```

## 项目材料与披露

本工程根据用户提供的 v0.1 计划搭建。课程要求、Decitron 相关描述和参考资料仍需小组在最终提交前逐项核对。Codex 参与了代码、测试、页面及文档起草；正式报告中的 LLM Usage Statement 应补充后续真实使用情况和人工核查记录。


## 2026-10-08 工作台与本地模型更新

默认工作台从空白研究开始；新建问题 → 分析与澄清 → 逐项处理前提 → 确认问题 → 联网取证与推演。页面不注入教学示例，也不从浏览器离线草稿恢复输入。教学固定响应仍用于隔离测试和兼容 API，不能作为真实结果。

保留树状阶段、来源、角色和行动分支；外围界面为原创研究目录、顶部问题与状态、按需展开的阅读区。支持节点阅读、分支折叠、缩放、轮次选择和全图定位。证据阅读保留前提/关系/来源筛选、失败候选隔离、快照哈希与 Unicode 码点引文校验。桌面和窄屏均支持键盘和触屏。

Brave 返回的描述与额外摘要按摘要身份保存，不伪装成全文或推断发布日期。请求以至少1.1秒的间隔启动；搜索专用代理由 `FORECASTLAB_SEARCH_PROXY` 配置，独立于模型服务。

专题研究由 `eval/research_supplement.py` 根据已冻结来源生成候选，原始调用留存在运行数据目录。核验通过后设置 `quality_status=reviewed` 和 `quality_review`；正文校订须逐段记录原始文本、修订文本与理由，导出器检查其与调用响应一致，再运行 `eval/publish_research.py --run-id RUN_ID` 发布。前端只显示已审核专题；重新构建前端后须重新执行发布脚本。候选质量状态和正式推演状态分别保存，专题不会伪造主链完成状态。

当前四卡部署说明见 [服务器部署](docs/server-deployment.md)，验收见 [2026-10-08验证记录](docs/validation-2026-10-08.md)。真实AI科研专题的 [审查后正文](docs/research/ai-science-2027.md) 与 [原始响应及事实校订审计](docs/research/research-run_eb86e9084513.json) 已分别保存；日期未知和截点后取证的限制不构成预测准确率验证。
