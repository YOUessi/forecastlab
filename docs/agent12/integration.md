# Agent 1–2 接口与证据流程

Agent 1 负责问题澄清、候选前提和用户确认；Agent 2 按确认后的研究目标整理来源、逐项发现、冲突与缺口。两者接入 ForecastLab 的完整研究工作台，向后续世界建模、主体行动、模拟、审查和报告提供可追溯输入。

启动与配置见 [项目说明](../../README.md)，请求示例见 [API 说明](api.md)，使用边界见 [产品局限](limitations.md)。接口的完整字段以 `backend/app/schemas.py` 和运行服务的 `/docs` 为准。

## 1. 问题分析、确认与运行

`QuestionFraming` 保存原始问题、规范化候选、用户输入、澄清、候选前提、替代方向、检索计划和分析记录。分析输出仍是候选，必须经过用户处理和服务端确认后才用于新版运行。

| 接口 | 契约 |
| --- | --- |
| `POST /api/questions/analyze` | 分析新问题或保存草稿新版本；修订时同时提供 `draft_id` 和 `expected_revision` |
| `GET /api/questions/{draft_id}` | 返回当前草稿、对应确认和准备阶段请求记录 |
| `POST /api/questions/{draft_id}/confirm` | 对本版本每项前提提交且只提交一个决定；存在未解决的阻断性澄清时拒绝确认 |
| `POST /api/runs` | 新版请求使用服务端 `confirmation_id` 创建运行，返回 202 和运行编号 |
| `GET /api/runs/{run_id}` | 查询运行状态及已保存结果 |

每次分析保存新的 `revision`。`operation_id` 用于同一输入的幂等重试；更换输入须使用新 ID。确认由数据库事务和版本比较保护：相同决定的重复提交返回同一确认，改变决定需生成新草稿版本。创建运行时再次检查确认是否仍对应最新版本，不能同时提交 `confirmation_id` 和另一份 `question`。

固定教学模式只接受指定案例及其约定输入；真实问题不能通过附加 `demo_case_id` 获得固定回答。教学确认与真实取证模式不能混用。

实现入口：[问题服务](../../backend/app/question_service.py)、[版本存储](../../backend/app/storage.py)、[服务接口](../../backend/app/api.py)。

## 2. 前提、证据与下游引用的边界

| 标识 | 对象 | 使用规则 |
| --- | --- | --- |
| P | `QuestionPremise` | 与用户原话关联的候选前提；确认其含义不等于确认事实为真 |
| E | `Evidence` | 当前运行的来源记录，保存来源元数据及原文快照引用 |
| F | `EvidenceFinding` | 对来源的逐项分析，通过 citations 回到 E；不增加独立来源数量 |
| H | `Assumption` | 用户指定或模型提出的建模条件，区分 `created_by` |
| M / S | 主体行动 / 模拟步骤 | 条件性推演记录，不能作为外部观察事实 |

前提决定控制后续用途：

| 决定 | 后续处理 |
| --- | --- |
| `retained + to_verify` | 交给 Agent 2 核查，不自动加入用户指定的 H 条件 |
| `retained + scenario_condition` | 作为用户指定条件映射为 H，并在 `premise_assumption_map` 记录 P → H；仍可接受证据核查 |
| `rejected` | 不进入有效发现或用户条件；包含该目标的检索任务整条移除 |

如果确认后没有可用检索任务，在线取证以研究问题生成中性背景查询。没有活动前提时，发现的 `target_premise_ids` 可以为空，不应虚构 P。

`findings_validated` 是服务端控制的状态。只有经过原文校验且 citations 指向当前 E 的 F，才可成为下游溯源节点。世界状态的 `evidence_refs` 和主体的 `visible_evidence_ids` 最终归一到 E；有效 F 可通过其 citations 展开为对应 E。`Assumption.parent_ids` 可以保留有效 E、F、H 关系。P 不能代替外部证据，未通过校验的候选不能进入这条依据链。最终报告分别校验来源、假设和模拟引用。

实现入口：[数据类型](../../backend/app/schemas.py)、[确认规则](../../backend/app/storage.py)、[下游引用适配](../../backend/app/graph.py)。

## 3. 取证、快照与原文定位

`online` 根据确认后的检索计划联网取证：配置 Brave 时优先使用 Brave，否则使用 Tavily。每批最多三个查询，跨查询去重和选择后最多保留十条来源。`import` 最多接受二十条材料。`reuse` 复制父运行的来源记录并重新生成发现，不复制父运行的发现；新运行的信息截至时间不能早于父运行，教学来源不能复用为真实证据。

检索按规范化 URL 和正文哈希合并精确重复项，并保留 query IDs、别名和日期元数据。明确转载线索用于来源分组；高文本重叠只标记疑似同源。`source_group` 不等于已核实的独立来源，不能按域名或来源数量推导独立佐证数。

正文在运行数据目录保存为 `sources-v1/<uuid>.json`，同时登记到 `source-index.sqlite3`。读取时核对登记记录、正文哈希、快照文件哈希和版本元数据，拒绝任意路径、符号链接及未登记文件。客户端声明的 `snapshot_path`、取得时间和日期状态不构成服务端的历史冻结证明。

单条正文最多保存 200,000 个 Unicode 码点，超出部分通过 `content_truncated` 标记。检索响应限制为 8 MiB，HTTP 请求超时配置为 25 秒。模型只接收选中的有界段落，不能据此认为它已读取来源全文。

`GET /api/runs/{run_id}/evidence/{evidence_id}/passages` 通过运行所属 E 加载已登记快照，返回正文、哈希、截断状态和段落。每段包括 `paragraph_id/start/end/text/snapshot_hash`。偏移采用 Unicode 码点，前端切片使用 `Array.from(text)`；高亮前还需核对哈希和逐字 quote。旧来源缺少可验证快照时返回 422，不补造原文位置。

实现入口：[来源处理](../../backend/app/sources.py)、[快照与段落](../../backend/app/provenance.py)、[原文接口](../../backend/app/api.py)。

## 4. 逐项发现与引用校验

`EvidenceFinding` 包含 `id/target_premise_ids/claim/relation/citations/limitation`。`relation` 可为 `supports/challenges/alternative/background/unclear`，描述发现与前提的关系；同一来源可以对不同前提产生不同关系。检索任务的 `challenge` 用途不会自动使结果成为反证。

服务端先检查目标 P 是否有效、E 是否属于当前来源、快照哈希及段落是否匹配，以及 quote 是否在指定段落逐字且唯一出现。`start/end` 由后端计算，模型不提供可信偏移。

随后进行确定性的 claim 边界检查，覆盖 quote 外的数字和日期、部分英文实体或来源标签、publisher 引入，以及“收盘”“官方”“固定提交”等限定。英文月份会归一为数字标记，允许对应的日期表达。这些检查针对常见越界模式，不构成完整的语义蕴含判断。

模型输出要求 claim 是 exact quote 的保守释义。quote 未写出的机构、年份、因果、标题上下文和来源身份应移到 `limitation` 或 `summary`；裸日期与数值不能擅自扩展为“收盘值”，也不能从片段没有提到某事件推断该事件没有发生。

结构和边界错误进入同一修复预算：初次分析后最多再请求一次修复。仍不符合要求的候选保留于 `rejected_findings`，不进入有效发现。该列表也可能包含不合格的冲突或缺口候选，应与 `findings` 分开使用。

实现入口：[发现校验](../../backend/app/agents/evidence.py)、[引文定位](../../backend/app/provenance.py)。

## 5. 证据质量概览

`EvidenceAssessment.quality_profile` 是可选的 `EvidenceQualityProfile`。后端根据来源、检索日志和校验结果确定性计算，不额外调用模型或搜索服务。正常取证、空来源和失败路径均可提供相应统计。

| 字段 | 统计口径与解释 |
| --- | --- |
| `source_count` | 当前保留的来源数；正常分析路径先排除无法验证的快照 |
| `source_group_count` | 当前来源组数，不代表独立来源认证 |
| `body_source_count` | `content_kind=body` 的来源数，不证明正文真实 |
| `snippet_only_count` | `content_kind=snippet` 或 `source_type=snippet_only` 的来源数 |
| `primary_label_count` | 标记为一手来源的数量，标记本身未独立核实 |
| `unknown_publication_count` | 缺少 `published_at` 的来源数 |
| `truncated_count` | `content_truncated` 为真的来源数 |
| `suspected_same_source_count` | 含 `possible_same_source` 线索的来源数 |
| `merged_alias_count` | 各来源 `max(0, aliases 数量 - 1)` 之和，不是新增来源数 |
| `search_success_count / search_empty_count / search_failure_count` | 检索日志中的成功、空结果和失败任务数；无在线查询时为零 |
| `excluded_count` | 来源或候选排除记录数 |
| `validated_finding_count` | `findings_validated` 为真时的有效发现数，否则为零 |
| `rejected_finding_count` | `rejected_findings` 记录数，包含被拒绝的发现、冲突或缺口候选 |
| `unresolved_conflict_count` | `status=unresolved` 的发现级冲突数 |
| `warnings` | 由来源覆盖、日期、摘要、截断、检索失败、排除和冲突等状态生成的限制说明 |

质量概览描述证据覆盖情况，不是事实可信度分数。World 和 Review 接收相应上下文；来源数量和来源组不能直接作为调整概率或自动阻断运行的阈值。前端证据面板和 HTML/JSON 导出保留质量信息及限制。未启用将研究性语义 judge 结果作为 Agent 2 生产准入条件的机制。

实现入口：[质量统计](../../backend/app/evidence_quality.py)、[质量类型](../../backend/app/schemas.py)、[工作流](../../backend/app/graph.py)、[报告导出](../../backend/app/api.py)。

## 6. 冲突导航与下游上下文

`ConflictDetail` 记录 `issue/finding_ids/scope_comparison/status/explanation`。前端从关联 F 读取有效 citations，按 E 去重生成来源入口，再复用原文查看与 quote 高亮。时间、地区或计量口径不同的发现不一定互相否定；导航只提供追溯入口，不从来源元数据创造冲突。

传入后续模型时，发现及支撑它的引文按整体保留。预算不足或段落不匹配时，同时省略发现并记录限制，避免留下没有引用内容的判断。被省略的发现不代表不存在相关证据。未通过校验的候选不作为有效事实传递。

实现入口：[证据面板](../../frontend/src/components/EvidenceFindingsPanel.tsx)、[上下文构建](../../backend/app/agents/evidence.py)。

## 7. 兼容、持久化与预算

`QuestionSpec` 和 `EvidenceAssessment` 的 `summary/evidence_ids/conflicts/gaps` 保留；兼容的冲突与缺口文本由结构化结果生成。旧运行的新字段使用空默认值，`quality_profile=None` 时不补造质量数据。缺少 `question_framing` 的页面说明历史记录未包含问题理解和逐项发现。

历史创建接口仍可单独传 `question`，运行标记为 `question_origin=legacy_direct`，不视为经过新版确认。已有运行保存其当时的问题与确认副本，供回放、结算和导出使用；修订不覆盖父运行。

新版问题准备和运行中的模型调用在发送前持久化预约。每个草稿的准备阶段最多六次请求；关联准备与运行共同受 `FORECASTLAB_MAX_CALLS` 限制，默认十八次，修复和重试也计入。`FORECASTLAB_MAX_SECONDS` 默认 300 秒；用户等待编辑的时间不计入模型活动时间，恢复沿用已保存消耗。未知 token 用量保留为未知，跨记录汇总应按 `request_id` 去重。

新版取证结果会持久化。同一运行恢复时复用已保存来源；若搜索批次已开始但在结果保存前中断，不重新发送搜索。重新联网取证需要创建新运行，不能把“从失败阶段继续”理解为无限重试。

JSON 导出删除 `snapshot_path/declared_snapshot_path`；导出中的来源编号和哈希不授予任意服务器文件读取能力。

实现入口：[持久化与版本](../../backend/app/storage.py)、[模型预算](../../backend/app/llm.py)、[恢复流程](../../backend/app/graph.py)、[配置](../../backend/app/config.py)。
