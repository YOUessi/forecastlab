# ForecastLab

基于证据溯源与多主体推演的预测研究工作台。用户提出一个可结算的二元事件或开放情景问题，系统依次完成问题确认、取证、世界建模、主体行动与环境推进、审查和报告生成，并保留可检查的来源与运行记录。

ForecastLab 是课程项目。多个 Agent 代表不同职责、输入范围和结构化输出，共用已配置的模型服务；预测概率属于未经校准的主观判断。

## 使用流程

1. **新建研究**：填写问题、信息截点、结算时间与规则；开放问题使用情景分析。
2. **确认问题**：回答必要澄清，逐项决定候选前提是待核查事实、指定情景条件，还是不采用。
3. **整理证据**：在线搜索或导入证据包，检查来源原文、逐项发现、冲突与缺口。
4. **检查推演**：查看世界状态、主体目标、两轮行动和环境变化；无可模拟主体时可以跳过行动推演。
5. **阅读报告**：检查审查结论、概率依据、来源引用和限制；从历史记录重新查看或导出 HTML/JSON。

正式界面是 Research Workspace：推演画布、问题与证据、主体与行动、研究报告四个阅读入口，共享同一条运行记录。教学回放使用固定虚构材料；生成新的真实研究需要配置模型服务。

## 快速启动

需要 Python 3.12、`uv`、Node.js 20.19+/22.12+ 和 npm。

首次配置时，将 `.env.example` 复制为本机 `.env`，然后启动：

```bash
cp .env.example .env
bash scripts/start-local.sh
```

打开 <http://127.0.0.1:8765>。启动脚本安装锁定依赖，并在缺少前端构建时执行构建。修改前端后可用 `REBUILD=1 bash scripts/start-local.sh` 重新构建。已有配置时直接运行启动脚本。

### 模型与搜索配置

| 用途 | `.env` 配置 |
| --- | --- |
| Qwen / OpenAI 兼容模型接口 | `QWEN_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL` |
| DeepSeek 接口 | `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` |
| Brave 在线检索 | `BRAVE_SEARCH_API_KEY` |
| Tavily 在线检索 | `TAVILY_API_KEY` |

两组模型配置同时提供密钥时，优先使用 `QWEN_*`。在线检索优先使用已配置的 Brave，否则使用 Tavily；没有搜索配置时可导入证据包。未配置模型服务时不能生成真实分析。密钥保存在本机或部署环境，运行数据保存在 `data/`。

证据包可以是 JSON 数组，或包含 `evidence` 数组的对象。每条资料提供来源标题、URL、发布方、发布日期及支持判断的原文；字段示例见 [API 与证据格式](docs/agent12/api.md)。后端分配证据编号、保存快照并计算内容哈希。历史回测的证据可用性需按信息截点单独核实。

### 开发与部署

前端开发服务器默认把 `/api` 代理到后端 8000 端口：

```bash
uv sync --locked
uv run uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 8000
# 另开终端：
cd frontend
npm ci
npm run dev
```

Docker 部署使用 `docker compose up -d --build`。应用本身没有账号和多用户隔离，默认仅监听本机；服务器访问控制、模型服务和持久化配置见 [部署说明](docs/server-deployment.md)。

## 系统结构

后端使用 FastAPI、LangGraph 和 SQLite，前端使用 React、TypeScript 和 Vite。主流程是六个阶段，主体行动与环境推进在模拟阶段内执行。

| 阶段 | 职责 | 主要实现 |
| --- | --- | --- |
| 问题 | 明确目标、候选前提、澄清与检索计划，保存用户确认 | `backend/app/agents/question.py`、`question_service.py` |
| 证据 | 获取资料、保存快照、生成带精确引文的发现，记录冲突和缺口 | `backend/app/sources.py`、`agents/evidence.py` |
| 世界 | 建立状态变量、主体画像、约束和假设 | `backend/app/graph.py` 中的世界节点 |
| 模拟 | 主体读取同一轮父状态并行行动，环境统一推进，最多两轮 | `backend/app/graph.py` 中的模拟节点 |
| 审查 | 核对判断依据，决定完整依据、仅证据或拒绝给出概率 | `backend/app/graph.py` 中的审查节点 |
| 报告 | 生成结论、引用、情景和限制，保存运行与导出内容 | `backend/app/graph.py`、`api.py`、`storage.py` |

接口文档位于运行服务的 `/docs`。主要业务入口包括问题分析与确认、创建运行、查询阶段与证据、恢复中断、导出报告，以及结算后二元 Brier 评分。详细契约见 [问题与证据 API](docs/agent12/api.md)，完整角色关系见 [工作流说明](docs/Agent工作流完整说明.md)。

### 结果边界

- 用户认可的前提仍需核查；指定情景条件作为假设保留。
- 外部证据、模型发现、假设和模拟结果有不同身份；模拟结果不会自动成为外部事实。
- 精确引用校验保证引文可定位，不能单独证明来源可靠或结论被原文完整支持。
- 完整模拟依据未通过审核时，可以另行审核仅证据依据；证据仍不足则不输出概率。开放情景的概率始终为空。
- 同一配置模型承担多个角色，不等于独立专家投票；少量已结算案例不能证明概率已校准。
- 影子全依据实验由 `FORECASTLAB_SHADOW=1` 单独启用，默认关闭，其输出不作为正式预测。

## 测试与正式实验

```bash
uv sync --locked --group browser
uv run pytest -q
uv run python experiment/validate_suite.py
npm --prefix frontend ci
npm --prefix frontend run build
uv run --group browser python -m playwright install chromium
uv run --group browser pytest frontend/tests -q
```

自动测试覆盖接口契约、问题确认、证据边界、状态推进、引用、失败恢复和浏览器工作流。固定教学样例与离线回归通过，不代表真实模型预测质量。

| 实验资料 | 范围 |
| --- | --- |
| [团队实验索引](experiment/README.md) | v1/v2/v3v4 的整体预测、证据、模拟依据和闸门对照 |
| [24 案例冻结历史评测](experiment-2026-10-07-v2/report.md) | 完整流程、单 Agent 同证据及无证据基线 |
| [真实在线全流程](experiment-2026-10-07-live-e2e/report.md) | 真实模型与 Tavily 经 HTTP 产品入口运行，含引用与最终状态校验 |
| [在线检索质量](experiment-2026-10-07-tavily/report.md) | Tavily 的查询覆盖、正文获取与元信息限制 |

各报告的模型、套件、日期和评分口径分别记录；不同实验轮次不能合并成同一成绩。当前记录没有证明多阶段模拟稳定提升预测准确率。新的实验结论应附对应代码版本、输入、结果及验证范围。

## 文档与目录

[文档索引](docs/README.md)提供完整工作流、API、部署、使用边界及正式项目材料的入口。

| 目录 | 内容 |
| --- | --- |
| `backend/app/` | API、数据契约、模型适配、工作流与持久化 |
| `backend/tests/` | 后端契约与回归测试 |
| `frontend/` | 研究工作台、来源阅读与浏览器测试 |
| `eval/` | 评测工具、冻结套件与回归所需数据 |
| `experiment/` | 团队正式实验及其索引 |
| `docs/` | 维护中的项目技术文档与团队交付资料 |
| `examples/` | 导入示例与明确标注的教学材料 |
| `deploy/`、`scripts/` | 部署配置与运行工具 |

共享仓库保留运行、维护、复现和团队交付所需资料。个人开发流水、修改过程、临时排障与自测记录保存在个人 fork；提交 PR 时选择与项目交付相关的改动。

## 项目披露

本项目使用 LLM 辅助代码、测试、界面与文档工作。课程提交应根据实际使用情况完成 LLM Usage Statement，并由小组核对实验事实、引用与最终结论。
