# v2 · 训练数据截止之后的评测套件（2026-10-07）

> 合并后的实验目录总览见上一级 [`../README.md`](../README.md)。

## 1. 为什么要开这轮实验

上一轮套件 `forecastlab-v1`（见 `../v1-2026-10-04/`）里，多数案例的事件发生在
2024–2025 年初，**早于本项目所用模型的训练数据截止时间**。后果是：

- `no_evidence`（只看模型自身知识）这一臂可能"记得"结果，而不是在真正做预测；
- 三条臂的对比被污染，无法判断框架相对"模型自身知识"到底有没有增益。

本项目使用的 DeepSeek 模型（`.env` 中 `DEEPSEEK_MODEL=deepseek-flash`，指向 V4 家族）
训练数据截止约 **2025 年 5 月**（依据：DeepSeek 的欧盟 "Public Summary of Training
Content"，DeepSeek-V4 含 Pro/Flash，"some data collected approximately no later than
May 2025"）。

本轮套件据此设计：**所有案例的 `as_of` 均 ≥ 2025-07-01**，即模型训练数据不可能覆盖；
事件结果在 **2026-10-01** 之前都已实际确定，因此仍可回测评分，但不存在训练数据泄漏。

## 2. 数据口径

| 项目 | 说明 |
| --- | --- |
| 判定口径 | 一律取**实际动作/实际结果**：实际发售、实际发射、实际赛果、官方声明实际发布的数值 |
| 证据 | 每条证据的 `published_at` 都 ≤ 该案例的 `as_of`（硬约束，已逐条校验） |
| 结果来源 | `resolution.source_url` 用最权威来源（官方机构、官方新闻稿、官方赛事页面） |
| 正负例 | 15 例中 10 个正例（outcome=1）、5 个负例（outcome=0），避免"恒看涨"退化解拿高分 |
| 已知局限 | 部分案例用媒体的赛前/赛况报道作证据，已在 `flags` 标 `SECONDARY_SOURCE`；部分负例与其正例共用同一证据包（窗口不同），存在相关性；单轮运行、未固定温度、未做重复性实验 |

## 2.5 评分口径与含义

每个案例先定一个客观结果 `outcome`（1 = 问题答案为"是"，0 = "否"）。每个臂对每个案例输出一个概率
`p = P(outcome = 1)`，给不出概率时记为弃权（`null`）。

| 指标 | 算法 | 含义 |
| --- | --- | --- |
| 覆盖率 | 给出概率的案例数 / 总案例数 | 敢不敢下注。只在简单题上出概率也算作弊，所以要配合下面的回退 Brier 一起看 |
| Brier（有效） | 对该臂**实际作答**的案例求 `mean((p − outcome)²)` | 概率准不准。0 为完美；0.25 等于"一律报 50%"的水平；越低越好，且同时惩罚方向错误与过度自信 |
| Brier（弃权按 0.5） | 对**全部**案例求 `mean((p − outcome)²)`，弃权按 `p = 0.5` 计 | 把弃权当作"报 50%"来计分，用于惩罚"拿不准就不答" |
| BSS vs 0.5 | `1 − Brier / 0.25` | 相对"一律 50%"的改进比例：**> 0 比瞎猜好，< 0 不如瞎猜** |
| BSS vs 基准率 | `1 − Brier / Brier(恒定基准率)` | 相对"一律报样本里正例的比例"的改进 |

两点约定：两个 BSS 都只在**该臂实际作答的案例**上计算（参考线同步重算），所以无法靠弃权刷分；
当参考线本身零误差（例如作答案例结果全相同）时，BSS 记为 `null` 而不是给一个无意义的数。
本套件正负各半，基准率恰为 0.50，因此两个 BSS 数值相同。

## 3. 案例清单（20 个：10 正 + 10 负）

### 正例（outcome = 1）

| ID | 类别 | 问题（是/否） | as_of | resolve_by |
| --- | --- | --- | --- | --- |
| PW1-worldcup-spain | sport | 西班牙是否赢得 2026 世界杯决赛？ | 2026-07-16 | 2026-07-19 |
| PW2-olympics-norway | sport | 挪威是否米兰-科尔蒂纳 2026 冬奥会金牌榜第一？ | 2026-02-21 | 2026-02-22 |
| PS3-nba-east-champ | sport | 2026 NBA 总冠军是否来自东部联盟？ | 2026-05-31 | 2026-06-30 |
| PT1-iphone17-launch | tech | Apple 是否在 2025-10-31 前实际发售 iPhone 17 系列？ | 2025-08-31 | 2025-10-31 |
| PT2-gpt5-public | tech | OpenAI 是否在 2025-09-30 前向公众发布 GPT-5？ | 2025-07-31 | 2025-09-30 |
| PT3-node24-lts | tech | Node.js 24 是否在 2025-12-31 前成为 Active LTS？ | 2025-09-30 | 2025-12-31 |
| PF1-fed-dec2025 | finance | 美联储是否在 2025-12-31 前的会议再次降息？ | 2025-10-31 | 2025-12-31 |
| PF2-fed-jan2026 | finance | 美联储是否在 2026-01-31 前的会议维持利率不变？ | 2025-12-31 | 2026-01-31 |
| PP1-artemis2 | public | Artemis II 是否在 2026-04-30 前载人绕月并安全返回？ | 2026-02-28 | 2026-04-30 |
| PP2-starship-flight11 | public | SpaceX 是否在 2025-12-31 前实际执行星舰 Flight 11？ | 2025-09-30 | 2025-12-31 |

### 负例（outcome = 0）

| ID | 类别 | 问题（是/否） | as_of | resolve_by | 实际结果 |
| --- | --- | --- | --- | --- | --- |
| PN1-premier-league-city | sport | 曼城是否夺得 2025/26 英超冠军？ | 2026-04-30 | 2026-05-31 | 阿森纳夺冠，曼城第二 |
| PN2-nba-west-champ | sport | 2026 NBA 总冠军是否来自西部？ | 2026-05-31 | 2026-06-30 | 东部尼克斯夺冠 |
| PN3-node24-early-lts | tech | Node.js 24 是否在 2025-09-30 前成为 Active LTS？ | 2025-08-31 | 2025-09-30 | 2025-10-28 才进入 LTS |
| PN4-fed-jan2026-cut | finance | 美联储是否在 2026-01-31 前的会议降息？ | 2025-12-31 | 2026-01-31 | 1 月维持不变 |
| PN5-artemis2-march | public | Artemis II 是否在 2026-03-31 前实际发射？ | 2026-02-28 | 2026-03-31 | 2026-04-01 才发射 |
| PN6-real-madrid-ucl | sport | 皇马是否夺得 2025/26 欧冠冠军？ | 2026-04-30 | 2026-05-31 | PSG 卫冕，皇马 1/4 决赛出局 |
| PN7-fed-mar2026-hold | finance | 美联储是否在 2026-03-31 前的会议降息？ | 2026-02-28 | 2026-03-31 | 3-18 维持不变 |
| PN8-worldcup-argentina | sport | 阿根廷是否赢得 2026 世界杯决赛？ | 2026-07-16 | 2026-07-19 | 西班牙夺冠，阿根廷亚军 |
| PN9-olympics-usa | public | 美国是否在米兰冬奥会金牌榜第一？ | 2026-02-21 | 2026-02-22 | 挪威 18 金第一，美国 12 金第二 |
| PN10-iphone17-deadline | tech | iPhone 17 是否在 2025-08-31 前发售？ | 2025-08-31 | 2025-09-30 | 2025-09-19 才开售 |

> PN6 / PN7 是新事件；PN8 / PN9 / PN10 与其正例（PW1 / PW2 / PT1）**共用同一证据包**、
> 只是问题方向或截止窗口不同（已在 `flags` 标注 `SHARED_EVIDENCE_WITH_*`），存在相关性。

## 4. 文件

| 路径 | 内容 |
| --- | --- |
| `suite/forecastlab-v2-postcutoff.json` | 20 案例套件（问题、信息截至、结算规则、结果、证据引用） |
| `suite/cases/*.json` | 冻结证据包（正负例共用的包只存一份） |
| `results/` | 正式运行后写入的结果表与评分（尚未生成） |

套件通过 `evidence_file` 引用证据包，路径相对仓库根目录解析，因此**无需把文件复制到
`eval/`**：`eval/run_suite.py` 可直接读取本文件夹。

## 5. 如何运行

在仓库根目录 `forecastlab/` 下执行：

```powershell
# 离线校验两个套件（不调用模型）
python experiment/validate_suite.py

# 只校验、不调用模型
conda run --no-capture-output -n forecastlab python eval/run_suite.py `
  experiment/v2-postcutoff-2026-10-07/suite/forecastlab-v2-postcutoff.json `
  --out data/eval/v2-postcutoff-dryrun.json --dry-run

# 正式跑三臂（full / single_agent / no_evidence），会消耗模型调用
conda run --no-capture-output -n forecastlab python eval/run_suite.py `
  experiment/v2-postcutoff-2026-10-07/suite/forecastlab-v2-postcutoff.json `
  --out data/eval/v2-postcutoff.json

# 评分
conda run --no-capture-output -n forecastlab python eval/score_table.py `
  data/eval/v2-postcutoff.json --group-by category
```

## 6. 状态

- [x] 20 个案例（10 正 + 10 负）与证据包已建好，离线校验通过（`as_of ≥ 2025-07-01`、证据日期 ≤ `as_of`、
      无重复 URL、`resolve_by > as_of`、outcome ∈ {0,1}）。
- [x] 模型名已从 `deepseek-chat` 改为 `deepseek-flash`（官方已把 `deepseek-chat` 列为 2026-07-24 停用）。
- [x] 三臂运行完成，结果见 `results/v2-postcutoff.json` 与 `results/v2-postcutoff-score.json`，
      分析见 [`report.md`](report.md)。历史结果保留在 `results/v2-postcutoff-15case*.json`
      （15 案例版）与 `results/v2-postcutoff-before-fix.json`（修复前基线）。

## 7. 结果摘要

20 案例版（正负各半，基准率 0.50）：

| 臂 | 覆盖率 | Brier（有效） | Brier（弃权按 0.5） | BSS vs 0.5 |
| --- | --- | --- | --- | --- |
| full | 0.75 | 0.148 | 0.174 | +0.406 |
| single_agent + 同证据 | 1.00 | 0.162 | 0.162 | +0.350 |
| no_evidence（仅模型知识） | 1.00 | 0.168 | 0.168 | +0.327 |

`no_evidence` 与两个带证据的臂接近，原因是这批案例中有很多"按公开日程可预测"的事件
（Node LTS 日程、Apple 9 月发新机、冬奥/世界杯按期举行）。详见 [`report.md`](report.md)。
