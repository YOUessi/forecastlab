# ForecastLab Agent 1/2 正式版本核对与上游整合审计（2026-10-08）

## 审计目的

解决分支同时开发导致的版本混淆：不要从聊天记忆复述所谓“最好版本”，而以**已提交代码、文件 blob SHA、可复现测试和真实实验记录**锁定正式 Agent 1/2。此审计对代码一致性负责，不承诺不存在任何未来发现的缺陷。

## 选用的基线（正式产品）

稳定参考：`YOUessi/forecastlab:main@aec25db6fbdb31609a26b9528de14f212d514370`，它已经通过之前的正式产品与 Agent 1/2 回归。2026-10-08 上游分叉后，整合分支 `integration/upstream-research-workspace-20261008` 同时保留 `hkuaidt/forecastlab@328859672c6b50e41fa7f010c828f2b81baba31c` 的完整研究工作台（非 Agent1/2-only UI）、Brave/Tavily、Qwen 本地适配、队友 v3/v4 实验。

逐文件审核（SHA-1 为 Git blob，不是运行内容哈希）：

| 文件 | 稳定基线 blob SHA | 处理 |
| --- | --- | --- |
| `backend/app/agents/question.py` | `7e7537f13368db6b987bb56811d4031b321cfbba` | 恢复此前实际评测过的完整提示词；未采用上游与整合时增加的冗余、未经对照的提示词变更 |
| `backend/app/question_service.py` | `f58f6a5f6ed0bbb7606328a33578ccaca92fab1f` | 字节相同，保留多轮澄清/确认/修订/幂等 |
| `backend/app/agents/evidence.py` | `f492424e2cabe2f98cc5db7dddaf7518451bad94` | 字节相同，保留 Exact Quote、Boundary-v2、拒绝候选、快照与引用校验 |
| `backend/app/provenance.py` | `bf9999c10b13006efd5e33a8966ec870f48e8a74` | 字节相同，保留完整原文和校验定位 |
| `backend/app/evidence_quality.py` | `c29079904ea26604e308d28b2691e8b188cc1337` | 字节相同，保留质量概览但不当成事实可信证书 |
| `backend/app/schemas.py` | `6e2191808cf2975cd24f376f115aa1564cf88b5a` | 字节相同，保留强结构、可信状态与旧记录兼容 |
| `frontend/src/components/EvidenceFindingsPanel.tsx` | `05f156933f15dd1b4e23c3020733839a8c734a69` | 字节相同，复用至上游新的 Research Workspace 页面 |

`backend/app/graph.py` **不是**旧版本原样覆盖：它需要同时支持最新上游的 Research Workspace、Brave 检索、Agent 1 确认、Agent 2 的 F→E 追踪、World/Review/Forecast 契约、可选 shadow。所有改动必须通过主项目的单元/集成/浏览器回归，而不能因融合失败放宽引用校验。

## 正式能力与禁止退化的约束

- Agent 1：不把预测目标本身误认成用户事实；不修改显式时间和结算字段；仅对阻断性歧义提问；用户逐项保留/否认/指定情景，确认前不开始正式运行。
- Agent 2：实际来源与模型 Finding 分离；有 `E→快照/哈希→段落→原文 quote→F→P` 追溯；quote 不支持的日期、机构、因果、来源身份不允许补进 claim；被拒绝的 Finding 不能进入有效事实链。
- 下游：只有 **server-validated** Finding 的 F 能成为 E 引用的桥梁；P 不是外部证据；World/Review 的 E/H/M/S 标识遵守服务端命名；来源数量、来源组不证明独立性，不自动修改概率；未来结果未知不等于截至日缺证。
- 前端：Agent1/2 是完整六阶段 ForecastLab 工作台的前两阶段，**没有额外 Agent1/2-only 首页按钮**；Evidence 页面保留质量限制与来源原文阅读。
- 实验：先前的 NLI、Qwen 1.5B/3B/7B-AWQ 独立 Judge 与 ensemble 未达成已定的 strict precision≥95% + recall≥90% 双目标，**不启用生产 hard gate**。

## 实际修复与测试（2026-10-08）

- CI #206 首次融合：`186 passed / 10 failed`。原因包括模型参数、Agent2→World 数据形态、F/E/H/M/S 引用、审查重试与情景输出约束。没有以删除测试作为方案。
- CI #208：`195 passed / 1 failed`。唯一剩余的冻结证据复用测试仍使用**旧版 FakeModel**，无法模拟当前 `evidence12` 的校验调用。
- CI #210/#212：定位 `FakeModel.complete()` 缺少新版模型调用参数，且旧 fixture 路径不满足最新版证据接口；此处是**测试替身过时**，不应绕过真实校验。
- CI #213（`37767515768`）：更新测试替身为 `evidence12` 逐字原文、真实段落与快照哈希后，**196 项后端测试通过**（仅 2 个依赖弃用警告），上游 v1/v2/v3v4 离线套件分别 24/24、20/20、20/20（总计 64/64），前端生产构建通过，Chromium **21 项端到端测试通过**。
- CI #213 后额外核对：恢复 `question.py` 为稳定的原始 Git blob `7e7537…`，以避免未作真实模型 A/B 的额外提示词改动；**必须在这次恢复后的最新提交再次确认 CI** 才能合入 Fork `main`。

## 尚未被自动化 CI 证明的事项

- 结构化引用定位、元数据边界校验 **不等于**充分的语义蕴含验证。上一轮 held-out Judge/ensemble 结果尚未通过 strict 95%/90% 联合验收门槛；没有理由宣称“语义判断 100%”。
- 过去的审计包含 simulated reviewer 项与有限 case group；**真正独立的第二人工评审、组间一致性和足量独立测试集仍未完成**。
- 目前 CI 是离线单测、工具模拟及浏览器集成检查；它不构成**本次最终整合版本**使用付费模型与 Brave/Tavily 的真实大规模线上质量评测。
- “最完美”不是工程验收状态。当前可以确认的是锁定已验证的 Agent1/2 核心文件、补齐上下游接口，并禁止未验证的实验性门槛进入生产。

## 合并边界

先通过 Fork PR #12 的最新 head CI，再将其合入 `YOUessi/forecastlab:main`。最终提交至小组 `hkuaidt/forecastlab:main` 还需要由有权限的 GitHub 账户创建/合并跨仓库 PR；当前 ChatGPT GitHub 应用未获 `hkuaidt` 写入授权，不能声称上游已合并。
