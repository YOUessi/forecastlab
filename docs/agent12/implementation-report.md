# Agent 1–2 实现记录

> 本文记录 ForecastLab 中 Agent 1（问题定义）与 Agent 2（证据）的实际实现、接口、数据流、测试结果和当前限制。
> 适用分支：`feat/agent12-question-evidence`
> 基线：`hkuaidt/forecastlab@bb4d339`
> 负责范围：Zhang Kaiqi、Wang Kongtao、Tang Naisheng 共同负责 Agent 1–2 及其前后端接口与页面。本记录描述模块实现，不重新分配三人内部个人贡献。

## 1. 为什么要改

项目提案要求 Agent 1–2 完成四件核心事情：

1. 把用户问题说清楚，而不是直接沿着用户措辞回答；
2. 识别用户问题里隐藏或显式的前提；
3. 围绕支持、挑战和替代解释组织证据；
4. 让关键判断可以回到具体来源、日期和原文。

原始版本已经有 `QuestionSpec`、在线搜索、证据数组和 LangGraph 流程，但问题阶段主要是字段检查和检索词生成，证据阶段主要是把搜索结果交给模型总结。它还缺少“用户确认”“前提身份”“逐项证据发现”“精确原文引用”和“版本化回放”。

因此本次不是重写 ForecastLab，而是在原项目上补齐 Agent 1–2 的完整闭环。

## 2. 最终流程

```text
用户原始问题
   ↓
Agent 1：问题理解
   ├─ 规范化问题候选
   ├─ 识别缺失/含糊信息
   ├─ 识别候选前提 P
   ├─ 提出其他值得核查的方向
   └─ 形成检索任务草案
   ↓
用户澄清 + 逐项处理前提
   ├─ retained + to_verify
   ├─ retained + scenario_condition
   └─ rejected
   ↓
不可覆盖的确认版本
   ↓
Agent 2：证据研究
   ├─ 按检索任务取证
   ├─ URL/内容去重
   ├─ 来源分组与限制标记
   ├─ 保存正文快照
   ├─ 选取相关段落
   ├─ 生成逐项 EvidenceFinding
   ├─ 校验 E / P / quote / snapshot hash
   ├─ 记录冲突与缺口
   └─ 形成下游证据上下文
   ↓
Agent 3–7
```

核心原则是：**问题、前提、证据、建模假设和模拟结果始终是不同对象。**

# 3. Agent 1：问题定义

## 3.1 输入

Agent 1 接收 `QuestionDraft`：

- `question`：用户原始问题；
- `as_of`：信息截止时间；
- `resolve_by`：结算时间；
- `resolution_rule`：怎样判断结果发生；
- `resolution_source`：结算来源；
- `mode`：binary / scenario；
- `user_assumptions`：用户手工填写的情景条件。

继续分析时还会带：

- `draft_id`；
- `expected_revision`；
- 用户对澄清问题的回答；
- `operation_id`，用于幂等和超时重试。

## 3.2 Agent 1 输出

主要输出是 `QuestionFraming`：

- `raw_question`：用户原话；
- `proposed_spec`：规范化问题候选；
- `clarifications`：需要用户补充的问题；
- `premises`：从用户措辞中识别出的候选前提；
- `alternative_directions`：其他值得核查方向；
- `retrieval_plan`：后续证据检索任务；
- `status`：需要澄清或等待确认；
- `revision`：草稿版本；
- `analysis_record`：模型、请求、耗时和验证模式。

## 3.3 前提 P 的身份

每条候选前提不是“事实”，而是一个等待用户决定的对象。

例如：

```text
用户原话：
“已经完成全部测试，所以肯定能按时发布吧？”

P001：全部测试已经完成
P002：测试完成就能保证按期发布
```

用户必须分别选择：

| 处理 | 含义 | 后续行为 |
|---|---|---|
| `retained + to_verify` | 这是我的意思，但需要核查 | Agent 2 去找证据，不能直接当事实 |
| `retained + scenario_condition` | 我要求把它作为情景条件 | 世界建模时映射为用户 H 假设 |
| `rejected` | 不是我的意思 | 后续取证和建模不再使用 |

最重要的约束是：

> 用户确认“这是我的前提”，不等于确认“这个前提是真的”。

## 3.4 澄清

如果问题存在会影响研究对象或结算口径的歧义，Agent 1 输出阻断性澄清。

教学例子中：

```text
问题：V2 能否在 11 月 15 日前发布？
澄清：这里的“发布”是可下载的正式版，还是测试版？
```

在用户回答之前，不能进入确认状态。

## 3.5 版本和确认

问题分析不是覆盖式修改，而是版本化保存：

```text
draft_id
  ├─ revision 1
  ├─ revision 2
  └─ revision 3
```

确认后产生服务端生成的 `confirmation_id`。新版创建运行时只提交 `confirmation_id`，而不是重新提交另一份问题文本。

这样避免：

- 用户确认 A，运行时却换成 B；
- 浏览器刷新后丢失确认状态；
- 并发修改覆盖前一个版本；
- 超时重试制造重复确认。

## 3.6 主要实现文件

| 文件 | 作用 |
|---|---|
| `backend/app/agents/question.py` | 问题输入整理、模型分析、结构校验 |
| `backend/app/question_service.py` | 草稿版本、调用、幂等、确认服务 |
| `backend/app/storage.py` | 草稿/确认/请求持久化 |
| `backend/app/schemas.py` | QuestionFraming / Premise / Clarification |
| `backend/app/api.py` | analyze / read draft / confirm API |
| `frontend/src/components/QuestionConfirmationPanel.tsx` | 澄清、前提处理、确认 UI |
| `frontend/src/components/useQuestionFraming.ts` | 刷新恢复和 dirty 状态 |

# 4. Agent 2：证据研究

## 4.1 带目标的检索任务

Agent 1 生成带目的和目标前提的 `RetrievalTask`，而不是只有 query。每个任务记录 query、purpose 和 target premise IDs。

## 4.2 跨查询候选选择

在线模式使用 Tavily。最多 3 个检索任务，每个任务先形成独立候选桶，再跨桶选择最终来源，避免第一个 query 占满最终 10 条来源。

## 4.3 去重和来源分组

做两层去重：

1. URL 规范化；
2. 内容哈希。

去重后仍保留 query IDs 和 alias 元数据。

`source_group` 不再简单等于域名。系统区分明确转载、疑似同源和独立来源。

## 4.4 原文快照

正文由后端保存到 `sources-v1/<uuid>.json` 并登记：

- snapshot path；
- snapshot hash；
- content hash；
- retrieved_at；
- 是否截断。

浏览器不能传任意系统路径，只能通过 `run_id + evidence_id` 读取该运行已登记的来源。

## 4.5 段落选择

系统把快照切分为 passage，根据问题、活动前提和替代方向选相关段落，给每段分配 `paragraph_id`，并保存 Unicode 码点级 start/end。

因此关键内容不必位于文章开头。

## 4.6 EvidenceFinding

Agent 2 的核心结果：

```text
F001
├─ target_premise_ids
├─ claim
├─ relation
├─ citations
└─ limitation
```

relation 包括 supports / challenges / alternative / background / unclear。

关系属于“这项发现与这个前提之间”，不是给整个网站贴立场标签。

## 4.7 精确引用校验

每个 citation 必须同时满足：

```text
有效 P
+ 有效 E
+ 正确 snapshot_hash
+ 存在 paragraph_id
+ quote 逐字存在
+ start/end 与 quote 对应
```

不满足就进入 `rejected_findings`，不能进入有效发现。

## 4.8 冲突和缺口

冲突结构记录：

- 争议点；
- 关联 findings；
- 时间/地区/指标口径；
- 是否已解释；
- 原因。

缺口区分：

- 检索失败；
- 没有结果；
- 只有 snippet；
- 发布时间未知；
- 来源晚于 cutoff；
- 引用校验失败。

未来实际结果尚未发生，不能被当作证据缺口。

## 4.9 主要实现文件

| 文件 | 作用 |
|---|---|
| `backend/app/sources.py` | 在线检索、候选选择、去重、来源分组、导入 |
| `backend/app/provenance.py` | 快照、hash、passage、原文定位 |
| `backend/app/agents/evidence.py` | findings、冲突、缺口、引用校验 |
| `backend/app/schemas.py` | EvidenceFinding / Citation / RetrievalResult |
| `frontend/src/components/EvidenceFindingsPanel.tsx` | findings 展示与筛选 |
| `frontend/src/App.tsx` | 来源抽屉、原文高亮、限制标签 |

# 5. Agent 1 → Agent 2 → Agent 3 的交接

```text
to_verify
  → Agent 2 核查
  → 不自动变成 H

scenario_condition
  → Agent 2 仍可核查
  → 世界建模时映射为 H
  → premise_assumption_map 记录 P → H

rejected
  → 不进入有效检索目标
  → 不进入有效 finding
  → 不进入 H
```

实际本地重跑验证：

```text
P001 = “全部测试已经完成”
treatment = scenario_condition
      ↓
premise_assumption_map = {"P001": "H002"}
      ↓
H002.created_by = user
H002.rationale = “用户明确指定的情景条件，不是已证实事实”
```

Agent 3–7 的主体策略和预测算法没有重写，只做输入适配、来源上下文和用户情景条件映射。

# 6. API

## Agent 1

- `POST /api/questions/analyze`：创建/更新问题草稿并运行 Agent 1。
- `GET /api/questions/{draft_id}`：读取草稿、确认和准备调用记录。
- `POST /api/questions/{draft_id}/confirm`：保存用户决定并生成 confirmation_id。

## Agent 2 / Run

- `POST /api/runs`：通过确认版本创建运行。
- `GET /api/runs/{id}/evidence`：读取来源。
- `GET /api/runs/{id}/evidence-assessment`：读取 findings/conflicts/gaps/logs。
- `GET /api/runs/{id}/evidence/{evidence_id}/passages`：读取登记原文和 passage。
- `GET /api/runs/{id}/export`：导出审计记录。

# 7. 前端实现

## 7.1 创建预测页

新增“先确认研究问题”：

1. 分析问题；
2. 显示系统理解；
3. 用户补充澄清；
4. 用户逐项处理前提；
5. 确认后才允许启动运行。

“体验问题与证据新流程”加载固定案例后会自动滚到 Agent 1，并把焦点放到“分析问题”。

## 7.2 证据页

支持：

- 按 premise 筛选；
- 按 relation 筛选；
- 按来源状态筛选；
- 查看 rejected findings；
- 打开来源抽屉；
- 精确高亮 quote；
- 展示 snippet-only / 日期未知 / 正文截断 / 来源分组依据。

## 7.3 历史与修改

修改已完成运行时，新建 child run，不覆盖 parent run。

# 8. 开发提交记录

| 顺序 | 提交 | 内容 |
|---|---|---|
| 1 | fe21126 | 固定基线时间测试 |
| 2 | b1cfec2 | framing / evidence 数据契约 |
| 3 | f0b6450 | 不可覆盖的问题确认 |
| 4 | 952865f | 调用预算与恢复 |
| 5 | f7504c1 | Agent 1 与确认 API |
| 6 | 9be12f2 | 来源快照与 passage |
| 7 | 5588faa | 多方向检索、去重和日志 |
| 8 | d04933c | Agent 2 findings 与原文校验 |
| 9 | 6729e4e | 接入 LangGraph |
| 10 | ca52de0 | Agent 1 前端 |
| 11 | f84c3b0 | Agent 2 前端 |
| 12 | 57f91e8 | 固定教学案例与评估入口 |
| 13 | 55400b2 | 边界问题修复 |
| 14 | 55464a9 | 验证与交接文档 |
| 15 | 8fdd1b8 | 教学入口点击反馈 |

# 9. 当前自动化结果

从最新 `origin/main` 新建 PR 分支后重新验证：

```text
Backend / packaging tests: 105 passed
Chromium browser tests:    15 passed
TypeScript + Vite build:   passed
Working tree:              clean
```

15 项浏览器测试中：

- 10 项用固定 API 响应验证 UI 状态机；
- 4 项使用实际本地后端验证教学入口在桌面/手机、普通/减少动画模式下正确显示下一步；
- 1 项不拦截 API，实际访问 FastAPI + SQLite + LangGraph，完整走固定 Agent 1–2 教学流程。

# 10. 实际 Web 全流程检查

除自动化测试外，还在本机 `127.0.0.1:8766` 实际点击：

- 首页和四个导航；
- 旧教学 Demo；
- Agent 1 教学入口；
- 自动滚动；
- 澄清；
- P001/P002 前提确认；
- Agent 2 findings；
- premise / relation 筛选；
- E002 原文；
- 精确高亮“两个高优先级兼容问题”；
- 两轮推演；
- Review；
- Forecast；
- 历史记录；
- HTML / JSON 导出；
- 修改条件并创建子运行；
- P001 → H002 情景条件映射；
- 无真实模型 Key 时明确失败，不伪造分析；
- 390px 手机宽度无横向溢出。

HTML 和 JSON 导出实际返回 HTTP 200。

# 11. 对照任务的当前状态

| 任务 | 状态 |
|---|---|
| 问题澄清 | 已实现 |
| 用户假设识别 | 已实现 |
| 用户确认与修订 | 已实现 |
| 前提和事实分离 | 已实现 |
| 检索计划 | 已实现 |
| 在线检索接口 | 已实现 |
| 导入证据 | 已实现 |
| 多方向候选选择 | 已实现 |
| URL / 内容去重 | 已实现 |
| 来源分组 | 已实现 |
| 来源快照 | 已实现 |
| 原文段落定位 | 已实现 |
| finding → premise → evidence → quote | 已实现 |
| 冲突和缺口 | 已实现 |
| 来源限制展示 | 已实现 |
| Agent 3–7 下游适配 | 已实现 |
| 前端问题确认 | 已实现 |
| 前端证据检查 | 已实现 |
| 历史回放兼容 | 已实现 |
| 固定教学演示 | 已实现 |
| 自动化工程测试 | 已实现 |
| 真实 LLM 语义质量评估 | **未执行** |
| 真实 Tavily 在线取证质量评估 | **未执行** |
| 人工原文支持率评估 | **未执行** |

最准确的结论：

> **Agent 1–2 的工程实现已经基本完成；剩余工作主要是用真实模型和真实检索做效果评估，而不是继续堆功能。**

# 12. 已知限制

## 12.1 真实模型尚未验证

固定教学模型能验证接口、状态、数据契约、引用安全和前后端交互，但不能证明真实 LLM 的假设识别、澄清质量和替代解释质量。

## 12.2 Tavily 尚未真实验证

真实网页环境中的正文抓取成功率、日期识别、转载识别、多 query 召回和 snippet-only 比例还没有形成实验结果。

## 12.3 自动校验不等于语义正确

代码可以证明引文存在、编号有效、hash 未变、quote/offset 对得上；但“原文是否真的充分支持 claim”仍需要模型审查和人工抽查。

## 12.4 多 Agent 不等于独立专家

多个角色共享同类模型时可能一起犯错，不能把“多个 Agent 一致”当作额外证据。

# 13. 下一步真实实验

建议冻结 5–10 个真实问题，覆盖：

- 中性问题；
- 明显带前提的问题；
- 含糊问题；
- 有冲突来源的问题；
- 缺少高质量资料的问题。

Agent 1 记录：

- 是否识别正确研究对象；
- 是否提出必要澄清；
- 是否识别用户前提；
- 是否把中性问题误判出前提；
- 用户是否需要修改模型理解。

Agent 2 记录：

- 检索方向是否真正不同；
- 有效来源数量；
- 一手来源比例；
- snippet-only 比例；
- 同源转载识别；
- finding 与 quote 的人工支持程度；
- 是否找到真正的挑战性证据；
- 是否出现无依据的平衡式反对观点。

同时记录 latency、tokens、模型调用数、搜索次数、失败和拒答。

# 14. 报告中目前可以写什么

可以写：

> 我们实现了一个版本化的问题定义流程，在启动预测前显式识别用户问题中的候选前提，并要求用户对每项前提选择“待核查”“情景条件”或“否认”。证据阶段使用带核查目标的检索任务收集资料，并将每项证据发现链接到具体前提、来源编号和保存的原文段落。系统使用服务端快照哈希、段落编号和逐字引用校验阻止不存在或错配的引用进入有效结果。固定教学案例和自动化测试验证了完整软件流程，但尚未完成真实模型语义质量和在线检索质量评估。

目前不能写：

- Agent 1 准确率达到 X%；
- Agent 2 引用支持率达到 X%；
- 多 Agent 显著优于单 Agent；
- 预测概率已经校准。

这些必须等真实实验完成后再报告。

# 15. 相关文档

- [API 说明](api.md)
- [Agent 1–2 与下游交接](integration.md)
- [验证记录](validation.md)
- [当前限制](limitations.md)
- [LLM 使用记录](llm-usage.md)
