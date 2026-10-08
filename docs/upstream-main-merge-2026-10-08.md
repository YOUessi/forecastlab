# 小组主仓库同步与完整 ForecastLab 产品入口 — 2026-10-08

## 目标与仓库基线

- 小组上游基线：`hkuaidt/forecastlab@34088e222dd1307efca7da8588043a2492817196`，含队友 PR #3 v3/v4 证据质量与 Review Gate 研究。
- 我的 Fork 基线：`YOUessi/forecastlab@49c40d5f74315814b236dc085e4b4bc103978696`，含 Agent 1/2 可靠性改进、证据质量汇总及完整产品 UI。
- 两边从 `0d2045d415b1637040d5af93f9dd3589375bc74d` 分叉；直接按 Fork 覆盖上游会遗失队友的实验和可选 shadow 功能。
- 整合采用有两个父提交的合并版本，保留双方提交历史与源代码，不修改任一已有 `main` 直到 PR 通过测试。

## 正式产品 UI

- **保留 Fork 的完整 ForecastLab 首页与四大导航区**：创建预测/问题确认、证据与世界状态、推演过程、结果与历史。
- 删除上游首页额外的 Agent1/2-only “体验问题与证据新流程”入口；保留固定、明确标记的全流程教学演示按钮和 Agent 1/2 的后端 fixture 自动测试。
- Agent 1 前提确认与 Agent 2 质量统计、来源冲突跳转只作为主流程的一部分；不增加独立 API 或演示子产品。

## 处理两套分支的代码交叉

- 上游 `experiment/` 下 88 个已提交文件**保持 blob 内容不变**，包括 v1/v2/v3v4 结果及校验脚本；Fork 中原有独立报告/评测目录也原样保留（旧 v1 目录可能重复，暂不删除任何一方历史材料）。
- `backend/app/config.py`：保留 Fork provider / temperature / live-cutoff，添加 `FORECASTLAB_SHADOW=0`（默认禁用）。
- `backend/app/graph.py`：保留 Fork 的 Agent 1/2 确认与来源校验、合法 F 中间节点、语义风险审查；整合上游 Finding→E 解析和软容错。**只有服务器验证过的 F 引文才允许扩展到 E**；非法定位编号不产生新来源。
- `backend/app/graph.py`：保留上游可选、失败不影响主预测的 `shadow_forecast`；主正式结果仍只使用 `forecast`，默认不增加任何模型调用。
- `backend/app/llm.py`：继承上游加大的结构化 JSON token 上限，保留 Fork 的服务商选择、温度与模型请求指纹以及关闭不适合 JSON 的思考模式。
- `backend/app/schemas.py`：保留 Fork 的 EvidenceQualityProfile / 校验标志，追加上游可选 `RunRecord.shadow_forecast`。
- `eval/run_suite.py`：保留 Fork 的 frozen cutoff validation 与逐阶段诊断，追加上游 `shadow_full_p` 与 `shadow_full_status` 指标。

## 无法机械沿用的上游差异

上游曾把所有 `unsupported_claims` 降成非阻断中等风险；Fork 版本已专门将“预测期未来结果未知”与真正未举证的历史主张区分开。为了避免静默放行**确有资料缺口的主张**，合并后继续沿用 Fork 的实质性 unsupported claim 阻断逻辑，但保留队友 v3/v4 对照实验与 shadow 能力。这项冲突取舍需要小组共同审阅，不应当假称两种策略完全相同。

## 验证与交付

- 新增 `backend/tests/test_upstream_merge.py` 约束：未校验 F 不得扩展为 E，合法 F 可扩展为 E，假设父节点保留中间 F，shadow 仅为可选字段。
- 保留 Fork 全部已存在的后端、前端与 Chromium E2E 测试（其中正式产品首页测试确保不存在独立 Agent1/2 入口）。
- 以整合分支最终 head 的 GitHub Actions 为合并前置条件；若有失败，不合并到小组主仓库。
- PR 合并后再次验证小组仓库 main SHA、完整前端入口、`experiment/` 的历史研究与 CI 结果。

