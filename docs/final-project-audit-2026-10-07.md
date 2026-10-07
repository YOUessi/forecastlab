# ForecastLab 全项目审计 — 2026-10-07

## 结论

ForecastLab 已达到课程项目可交付状态：核心业务链、证据溯源、状态持久化、失败恢复、前端工作台、历史回测、真实在线检索和真实模型 Live E2E 均有实际测试记录。它不是一个只靠 fixture 或页面演示的原型。

当前不应继续增加新的 Agent。剩余工作应集中在 Docker 环境网络验证和最终报告/演示；第二位独立真人角色的盲审模拟、PR/CI 与 fork main 收敛已经完成。

同时，本项目仍不是生产 SaaS：没有账号/权限隔离，运行队列为单实例锁 + FastAPI background task，概率未经校准，World/Actor/Simulation 尚未证明提高预测准确率。

## 1. 核心工程回归

最终核心测试链在本机完整执行：

- Backend: **152 passed**, 2 dependency warnings.
- Frontend production build: **passed**.
- Browser E2E: **13 passed**.
- `git diff --check`: passed.
- Docker Compose configuration: passed.
- Compose/systemd 默认均绑定 `127.0.0.1`，避免无认证服务直接暴露公网。

Moore Threads 组合分支从 GitHub 重新下载干净 checkout 后：

- Backend: **156 passed**, 2 dependency warnings.
- Frontend production build: passed.
- Browser E2E: **13 passed**.

GitHub Actions CI 已加入仓库，步骤与本机实际通过的命令保持一致。正常 PR 已真实触发 CI run #13 并全部通过；合并到 fork `main` 后 push CI run #14 也全部通过，已确认 Actions 链路有效。

## 2. 历史完整 Pipeline

冻结的 ForecastLab-v2 24-case Full run 使用真实 DeepSeek 模型：

- 19/24 输出概率，coverage 79.17%.
- 5/24 abstain / insufficient evidence.
- hard failure: **0**.
- answered Brier: **0.1448**.
- 0.5 abstention fallback Brier: **0.1667**.

Baseline:

- Single Agent + same evidence: **0.1443**.
- Single Agent without evidence: **0.1881**.
- matched 19 cases: Single + evidence **0.1265**, Full **0.1448**.

因此可以说 Evidence 明显有价值，但不能说 World/Actor/Simulation 已经提高预测准确率。

## 3. Agent 1 / Agent 2

Agent 1 before/after:

- explicit leading premise detection: **100%**.
- explicit field preservation: **100%**.
- unexpected neutral premise: **0%** after repair.
- blocking clarification: **0%** after repair.
- ready for confirmation: **100%** after repair.

Agent 2 single-reviewer exact-quote semantic audit:

- strict support: **50% → 90%**.
- lenient support: **100% → 100%**.

第二位独立真人角色的**盲审模拟**已完成：Reviewer 2 按独立真人评审协议，仅基于去除 Reviewer 1 标签/备注后的 30 条 blind packet 逐条判断，再与 Reviewer 1 结果计算一致性。

模拟 Reviewer 2：23 条 `supported`，7 条 `partially_supported`。与 Reviewer 1 的 raw agreement 为 **86.67%**，四分类 Cohen's κ 为 **0.534884**，strict-support binary κ 为 **0.534884**。4 条分歧均集中在“exact quote 支持核心事实，但日期、机构或来源归属来自 quote 外上下文”的边界情况。

这里的“第二位独立真人”是**评审角色模拟**，用于课程项目的盲审与一致性流程演练，不声称存在另一名真实自然人评审者。

## 4. 真实 Tavily 在线检索

生产 `retrieve_evidence()` 的 live benchmark:

- 8/8 cases completed.
- 16/16 retrieval tasks succeeded.
- selected evidence: 80.
- query coverage: **100%**.
- body-content rate: **97.5%**.
- snippet-only rate: **2.5%**.
- expected authoritative-domain hit rate: **100%**.
- date metadata rate: **0%** in this run.

最后一点很重要：Tavily 当前适合实时搜索，但今天搜索到的页面不能据此证明“历史 cutoff 前已经可用”。历史 backtest 继续要求 frozen / verified evidence 是正确的设计。

## 5. 真实模型 + 真实 Tavily Live HTTP E2E

最终 run 4 通过正式 HTTP API，而不是直接调用内部 agent 函数：

```text
HTTP question
→ Agent 1
→ confirm
→ Tavily
→ Agent 2
→ World
→ Simulation
→ Review
→ Forecast
→ persisted run / citation replay
```

三个 prospective cases:

| Case | Status | Evidence | Findings | Exact citations | Probability basis |
| --- | --- | ---: | ---: | ---: | --- |
| Python 3.15 | completed | 10 | 10 | 15 | evidence_only |
| Arsenal Top 4 | completed | 10 | 12 | 17 | evidence_only |
| Artemis III | completed | 10 | 13 | 13 | evidence_only |

Aggregate:

- completed: **3/3**.
- hard failures: **0**.
- validated Agent 2 findings: **35**.
- exact citations checked: **45**, failures **0**.
- final invalid references: **0**.
- model calls: **28**.
- prompt tokens: **626,886**.
- completion tokens: **31,793**.
- summed case wall time: ~148.5s.

真实 Live 测试暴露并修复了此前冻结数据测试没有覆盖的问题：

1. near-cutoff 实时检索时间语义；
2. “最终积分榜/最终排名”被误判为当前 evidence gap；
3. Review 偶发把 Retrieval Task ID 当作 affected_id 导致运行失败；
4. 每个来源重复生成“发布时间未知” gap；
5. live 网页 passage 过长导致 Agent 2 completion token exhaustion；
6. model-generated actor / assumption ID 命名不稳定。

这些问题均增加了回归测试，最终核心后端总测试数为 152。

## 6. Live E2E 的重要负结果

三个 live case 都执行到了 World/Simulation/Review，但 Review 都阻断了 full simulation 分支。最终概率由独立的 evidence-only audit 放行，因此三条结果全部使用 `probability_basis=evidence_only`。

这是 fail-closed 行为，不是崩溃，也不应为了让 Simulation “通过”而降低 Review 标准。

当前最准确的项目结论是：

> ForecastLab 能够完整执行在线多阶段流程，在模拟分支缺乏足够依据时阻断该分支，并回退到可追溯的 evidence-only forecast。

不能写成：

> multi-agent simulation 已证明提高 forecast accuracy.

## 7. Docker / 部署

已验证：

- Docker daemon 可启动.
- `docker compose config` 通过.
- Compose 和 systemd 默认 loopback-only.
- 临时 `.env` 不进入 Git.

实际 `docker compose build` 曾尝试，但 Docker Desktop 拉取 `docker/dockerfile:1.7` 时访问 Docker Hub auth endpoint 超时。失败发生在获取基础镜像/build frontend 之前，属于当前 Docker Hub 网络环境问题，不是 Dockerfile 语法或应用启动错误。

网络恢复后应再执行一次：

```bash
docker compose build
docker compose up -d
docker compose ps
```

并通过固定教学 demo 做容器内完整 run。

## 8. 当前仍需完成

### 最终提交前建议必须完成

1. 从已收敛且 CI 通过的 fork main 发 upstream PR.
2. Docker Hub 网络可用后补一次实际 container build/run.

### 课程加分项

- Moore Threads provider 已实现并完成 fake OpenAI-compatible endpoint / 回归测试。
- 真正 Moore Threads GPU profiling / benchmark 仍未完成，不能声称实际硬件性能数字。

### 非课程必须项

若要发展为公网生产系统，还需要：

- authentication / authorization / per-user data isolation;
- API quota / rate limiting;
- durable job queue + worker;
- multi-instance concurrency control;
- secrets manager;
- observability / metrics / alerting;
- database migration strategy.

这些不建议在当前课程项目阶段继续扩展。

## 9. 封版建议

第二位独立真人角色盲审模拟、分支收敛和真实 PR/CI 已完成；Docker 网络恢复后补一次容器 smoke，即可封版。

不建议继续添加 Agent、增加 simulation rounds 或为了让 Full 分支通过而放松证据审查。下一阶段如果做研究，应从“为什么 evidence-conditioned single agent 不弱于 multi-agent simulation”这一实证矛盾出发，而不是继续堆复杂度。
