# ForecastLab Agent 2 证据质量与冲突可视化补充 — 2026-10-08

## 背景与范围

以同学的 `forecastlab-evidence-agent` 为对照，我们只吸收对 ForecastLab **完整多 Agent 工作流**有用的能力：

1. 把采集/验证结果汇总成一份可追溯的 **Evidence Quality Profile**；
2. 让用户能从已验证的冲突 Finding 直接定位涉及的来源及原文；
3. 在既有 World → Review → Forecast 流程中传递证据覆盖和质量限制，并在最终报告保留这些限制。

**明确不做**：新增独立 `/api/evidence/collect`、独立 Agent1/2 演示或替换原来的来源快照/Exact Quote/Boundary-v2 校验。

## 数据流

```text
Agent 1: Question framing → confirmation → retrieval plan
  ↓
Tavily / import / reuse / fixed classroom evidence
  ↓
Agent 2: source snapshots → passages → quoted findings → boundary validator
  ├─ RetrievalResult.retrieval_log / exclusions
  ├─ Evidence.source_group / aliases / content_kind / date status
  ├─ EvidenceAssessment.findings / rejected_findings / conflict_details
  └─ EvidenceQualityProfile (后端确定性计算，不再调用 LLM)
  ↓
World → Review (包含 quality_profile 及原始溯源限制)
  ↓
Forecast → 当前证据页面 / HTML、JSON 运行报告
```

## 实现文件

- `backend/app/evidence_quality.py`：纯确定性统计；不触发在线检索或任何模型。
- `backend/app/schemas.py`：`EvidenceQualityProfile`，作为 `EvidenceAssessment.quality_profile` 的可选字段，兼容旧记录。
- `backend/app/agents/evidence.py`：有效来源快照检查后，结合最终 findings/rejected/conflicts 计算；失败与空来源分支也保留质量信息。
- `backend/app/graph.py`：Review 已经收到 `evidence_assessment`，明确告知模型阅读其中的质量限制，不把统计结果作为事实或自动 blocked 的阈值。
- `frontend/src/types.ts`：前端响应类型。
- `frontend/src/components/EvidenceFindingsPanel.tsx`：原有 Evidence 页显示质量指标、警告；从冲突 Finding 反查有效引用并调用既有 `onInspectCitation`。
- `frontend/src/style.css`：质量网格和小屏布局。
- `backend/app/api.py`：现有 HTML 导出同步展示质量数据；JSON 导出通过现有运行对象自然包含字段。

## 统计口径

| 字段 | 来源 | 解释及局限 |
| --- | --- | --- |
| `source_count` | 真实保留的 Evidence 数组 | 只有成功通过来源快照校验的资料计入 |
| `source_group_count` | 当前 Evidence.source_group 集合 | **来源组≠已经核实的独立来源**；不能按域名替代源头判断 |
| `body_source_count` | content_kind=body | 代表取得正文，不保证内容真实 |
| `snippet_only_count` | snippet/source_type=snippet_only | 搜索摘要不能伪装成正文 |
| `primary_label_count` | source_kind/source_type 一手标记 | 仅记录已标注类别，不构成第三方权威认证 |
| `unknown_publication_count` | published_at 缺失 | 取得日期不证明历史截止日已存在 |
| `truncated_count` | content_truncated | 保存正文不足以证明全文上下文 |
| `suspected_same_source_count` | possible_same_source | 标记疑似同源，不擅自合并 |
| `merged_alias_count` | max(0, aliases-1) 之和 | 同一个来源已有的重复/别名记录，非独立来源数 |
| `search_success/empty/failure_count` | retrieval_log | import/demo 无在线查询时各项为 0 |
| `excluded_count` | exclusions | 记录检索、发布日期、快照校验排除 |
| `validated_finding_count` | findings_validated + findings | 只计入通过现有校验流程的发现 |
| `rejected_finding_count` | rejected_findings | 不能作为下游事实 |
| `unresolved_conflict_count` | conflict_details | 未解决冲突需要保留解释和引用 |

注意：结构校验、哈希与原文定位只能证明**引文存在且未被篡改**，不能自动证明 claim 在语义上成立；本功能不虚构新事实，也不把 Reviewer 的验证结果写成来源真实性证明。

## 冲突来源导航

利用原有 `ConflictDetail.finding_ids` 找到有效 `EvidenceFinding.citations`；按 E 编号去重后展示来源链接；点击直接使用现有的原文抽屉和 quote 高亮。

因此不改变冲突模型的含义：**不同时间、地区、计量口径的发现不一定互相否定**。前端只是让用户追溯，不从来源元数据凭空创造冲突。

## 安全、兼容与生产限制

- 不修改 Agent 1 的用户确认、前提、检索计划等契约。
- 不扩充搜索次数，不增加 API 消耗，不保存模型密钥或外部链接内容。
- `quality_profile=None` 兼容旧版历史运行；前端不补造历史质量数据。
- 模型会收到质量提示，但 **不能通过来源数量直接调整概率，也不自动设置 hard gate**。
- Evidence-only fallback、Review 和 Forecast 原有校验路径不变。
- 固定教学演示的来源仍然显示教学/历史限制，不能声称是盲测。
- 不在这个 PR 中启用未达标的 NLI/Qwen Semantic Judge。

## 验收

包含后端纯函数测试、完整 confirmed → evidence → world → review → export 流程断言、无来源/检索失败分支、固定教学流程和浏览器证据冲突来源跳转。结果以 PR 最新 head CI 为准，未跑完之前不声称全部通过。
