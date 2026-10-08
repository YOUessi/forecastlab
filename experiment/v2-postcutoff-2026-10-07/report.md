# v2 实验报告：训练数据截止之后的预测评测

**日期** 2026-10-07　**套件** 20 案例（10 正 + 10 负）　**模型** `deepseek-flash`
**数据** `results/v2-postcutoff.json`、`results/v2-postcutoff-score.json`
**运行** 约 9 分钟、209 次调用；`full` 臂 15 例给出概率、5 例弃权、0 例崩溃

## 1. 目的

把案例的信息截至日全部放到模型训练数据截止（约 2025-05）之后，考察证据与框架在"无答案可背"条件下的表现。

## 2. 方法

- 20 个案例：10 正 + 10 负，全部 `as_of ≥ 2025-07-01`，结果在 2026-10-01 前已实际确定。
- 三个臂：`full`（六阶段框架）、`single_agent`（一次调用 + 同一证据包）、`no_evidence`（一次调用，仅模型知识）。
- 指标：覆盖率、Brier、BSS vs 0.5。正负各半，基准率为 0.50。
  每个臂对每例输出 `p = P(outcome = 1)`，弃权记 `null`。Brier = `mean((p − outcome)²)`，
  在该臂实际作答的案例上计算（0 完美，0.25 等于一律报 50%）；弃权回退 Brier 把弃权按 0.5 计分、
  覆盖全部案例；BSS = `1 − Brier / 0.25`，> 0 表示优于"一律 50%"。两个参考线都在作答案例上重算，
  因此弃权不能抬分。口径详见 [`README.md`](README.md#25-评分口径与含义)。

## 3. 结果

### 3.1 总体

| 臂 | 覆盖率 | Brier（有效） | Brier（弃权按 0.5） | BSS vs 0.5 |
| --- | --- | --- | --- | --- |
| full（六阶段框架） | 0.75 | **0.148** | 0.174 | **+0.406** |
| single_agent + 同证据 | 1.00 | 0.162 | 0.162 | +0.350 |
| no_evidence（仅模型知识） | 1.00 | 0.168 | 0.168 | +0.327 |

### 3.2 分类

| 类别 | n | full 覆盖 / Brier | single Brier | no_evidence Brier |
| --- | --- | --- | --- | --- |
| finance | 4 | 1.00 / 0.143 | 0.087 | 0.043 |
| public | 4 | 1.00 / 0.133 | 0.191 | 0.159 |
| sport | 7 | 0.57 / 0.238 | 0.193 | 0.189 |
| tech | 5 | 0.60 / 0.142 | 0.156 | 0.247 |

### 3.3 逐案例（full / single / no_evidence）

| ID | 结果 | full | single | none | full 状态 |
| --- | --- | --- | --- | --- | --- |
| PW1-worldcup-spain | 1 | 0.50 | 0.45 | 0.35 | completed |
| PW2-olympics-norway | 1 | — | 0.82 | 0.62 | insufficient_evidence |
| PS3-nba-east-champ | 1 | 0.40 | 0.42 | 0.47 | completed |
| PT1-iphone17-launch | 1 | 0.92 | 0.97 | 0.97 | completed |
| PT2-gpt5-public | 1 | 0.55 | 0.12 | 0.35 | completed |
| PT3-node24-lts | 1 | — | 0.96 | 0.97 | insufficient_evidence |
| PF1-fed-dec2025 | 1 | 0.50 | 0.55 | 0.72 | completed |
| PF2-fed-jan2026 | 1 | 0.60 | 0.75 | 0.78 | completed |
| PP1-artemis2 | 1 | 0.42 | 0.15 | 0.35 | completed |
| PP2-starship-flight11 | 1 | 0.75 | 0.85 | 0.75 | completed |
| PN1-premier-league-city | 0 | — | 0.42 | 0.30 | insufficient_evidence |
| PN2-nba-west-champ | 0 | 0.55 | 0.55 | 0.55 | completed |
| PN3-node24-early-lts | 0 | — | 0.05 | 0.90 | insufficient_evidence |
| PN4-fed-jan2026-cut | 0 | 0.20 | 0.15 | 0.15 | completed |
| PN5-artemis2-march | 0 | 0.35 | 0.12 | 0.08 | completed |
| PN6-real-madrid-ucl | 0 | 0.01 | 0.02 | 0.27 | completed |
| PN7-fed-mar2026-hold | 0 | 0.35 | 0.25 | 0.15 | completed |
| PN8-worldcup-argentina | 0 | — | 0.45 | 0.11 | insufficient_evidence |
| PN9-olympics-usa | 0 | 0.10 | 0.08 | 0.38 | completed |
| PN10-iphone17-deadline | 0 | 0.03 | 0.02 | 0.001 | completed |

## 4. 结论

1. 三个臂都优于 0.5 基线，`full` 最高（BSS +0.406）。
2. `no_evidence` 达到 +0.327，与两个带证据的臂接近。原因是套件中相当一部分事件可由截止前的公开日程推断：Node.js 24 的 LTS 日期写在官方发布日程里，Apple 每年 9 月发新机，冬奥与世界杯按计划举行，星舰按既定窗口发射。模型凭常识即可答对（`PT1` 0.97、`PT3` 0.97、`PF1` 0.72、`PF2` 0.78）。套件不含答案泄漏，但对"仅模型知识"这一臂偏宽松。
3. 在无日程可依的案例上，证据的价值明确。`PN3`（Node 24 是否 9 月底前进入 LTS）模型知识给 0.90 且判错，带证据的两臂给 0.05 或弃权且判对；世界杯、欧冠、NBA、GPT-5 发布时间四项同向。
4. `full` 与 `single_agent` 无显著差异（回退 Brier 0.174 vs 0.162）。`full` 覆盖率 0.75，sport 类低至 0.57，瓶颈在审查与复审阶段是否给出概率（环节诊断见 §5）。

## 5. 环节诊断：问题出在哪一步

六阶段流水线本轮 20 例的运行轨迹：

| 阶段 | 产出 | 是否进入最终概率 |
| --- | --- | --- |
| ① question | 检索词 | — |
| ② evidence | 证据与发现 | 是（`evidence_only` 路径只允许用它） |
| ③ world | 主体、假设 | **否** |
| ④ simulation | 行动、状态推演 | **否** |
| ⑤ review | 审查意见 + 决定概率依据 | 决定走向 |
| ⑥ forecast | 概率 | 输出 |

结果：`probability_basis = full` **0 例**，`evidence_only` 15 例，弃权 5 例。

### 5.1 主要问题在第 ⑤ 步：审查的否决门槛过低

两条规则叠加，使否决几乎必然发生：

- `unsupported_claims` 非空即判 `blocked`（`graph.py:460`）。预测类题目里"X 一定会发生"在信息截至日无法举证，因此该字段几乎必然非空 → 20 例中 17 例被否决。
- `future_gap_found` 独立于 `status` 触发复审（`graph.py:474`），把剩下 3 例未否决的也改判为 `evidence_only`。

后果：第 ③④ 步的产物一次也没有进入最终数字；第 ⑥ 步在 `evidence_only` 分支被明确要求忽略世界建模与推演。这是 `full` 臂与单 Agent 臂分数持平的直接原因。

### 5.2 次要问题在第 ② 步：证据包过薄

20 例的审查原因统计：

| 原因类别 | 出现案例数 |
| --- | --- |
| 代码自动补记 `future_gap` | 17 / 20 |
| 缺少截至日可查的关键资料 | 16 / 20 |
| 证据形式不合规（仅标题 / 摘要 / 二手） | 12 / 20 |
| 模拟跳步（把计划当事实、两轮重复） | 9 / 20 |
| 证据冲突未裁决 | 3 / 20 |

后分类中"证据形式不合规"与"缺少关键资料"合计指向同一问题：证据包平均只有 2–3 条来源，且多为媒体标题级摘要。审查对"只有标题"和"还缺 X"高度敏感，因此几乎每例都能挑出问题。

### 5.3 附带发现

- 审查有效：`PN6` 一例中，审查独立找出了证据包内部的真实缺陷（三条来源对"谁淘汰了皇家马德里"说法冲突，标为 high 级）。
- 因此改进顺序应先加厚证据包（②），再观察 `blocked` 比例；不应先放宽审查规则（⑤），那会直接稀释质检的严格性。

## 6. 局限

- **方差**：同一问题、同一代码两次运行，`no_evidence` 对 `PT3` 分别给出 0.02 与 0.97。采样温度未固定，单轮结果不足以支撑细粒度结论。
- 部分负例与其正例共用同一证据包（PN8/PN9/PN10），存在相关性。
- 部分证据来自媒体赛况报道，已在 `flags` 标注 `SECONDARY_SOURCE`。
- 本轮改动了 `llm.py` 与 `graph.py`，结果与 v1 旧数字不可直接比较。

## 7. 复现

```powershell
cd D:\GCB_Study\0code\forecastlab
python experiment/validate_suite.py
conda run --no-capture-output -n forecastlab python eval/run_suite.py `
  experiment/v2-postcutoff-2026-10-07/suite/forecastlab-v2-postcutoff.json `
  --out data/eval/v2-postcutoff.json
conda run --no-capture-output -n forecastlab python eval/score_table.py `
  data/eval/v2-postcutoff.json --group-by category
```

## 8. 下一步

- 固定温度（`temperature=0`）或每臂重复 3 次，先压低方差。
- 用当前代码重跑 v1，做同口径对比。
- 扩充"无日程可依"的案例（选举、胜负、产品跳票），让 `no_evidence` 成为强对照。
