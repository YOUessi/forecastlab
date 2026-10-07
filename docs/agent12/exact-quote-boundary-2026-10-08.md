# Agent 2 exact-quote claim boundary refinement — 2026-10-08

## Goal

Tighten the boundary between `finding.claim` and its cited exact quote without changing the Agent 2 architecture.

The existing server already verifies that a citation quote exists verbatim in the stored snapshot/passage. The remaining failure mode is semantic metadata leakage: a claim may add a date, year, publisher, organization, project/provenance label, or other context that exists in source metadata but not in the exact quoted span.

## Implementation

`backend/app/agents/evidence.py` now applies a second deterministic validation layer after citation resolution:

1. compare numeric/date markers in the claim against the combined exact quotes;
2. normalize English month names so translations such as `April 1` ↔ `4月1日` remain valid;
3. inspect English named markers from the cited source title/publisher and reject them when they appear in the claim but not in the exact quote;
4. reject publisher text copied into the claim when the quote itself does not state it;
5. feed the boundary violation into the existing single repair budget so Agent 2 gets one chance to rewrite the claim conservatively or move the extra context to `limitation` / `summary`;
6. if the repaired candidate still crosses the boundary, exclude the finding.

The prompt now explicitly states that title/publisher metadata cannot be promoted into `finding.claim`.

## Historical 30-item boundary audit

The new deterministic rule was applied to the previously blind-reviewed 30-item Agent 2 sample.

- Total sample: **30**
- Findings with no newly detected boundary leak: **21**
- Findings caught by the new boundary validator: **9**

The nine caught cases are:

| Case | Finding | Boundary leak |
| --- | --- | --- |
| C22-ndx-h2-2025 | F002 | claim adds `2025-06-30`; quote only states the index moves |
| C15-artemis2-complete | F002 | claim adds `NASA`; quote says only “The agency” |
| C09-man-city-top4 | F002 | claim adds `2024/25` fixture-release context |
| C11-usa-paris-gold | F002 | claim adds `Gracenote`; exact quote only gives Virtual Medal Table / US 39 gold |
| C13-worldcup-southamerica | F001 | claim adds `2026 年 4 月` and `FIFA`; quote only gives ranking order |
| C01-python313 | F001 | claim adds `Python`; quote itself starts from version `3.13.0rc2` |
| C01-python313 | F003 | claim adds `PEP 719` provenance |
| C04-starship-orbit | F001 | claim adds year `2025`; quote says only Jan. 16 |
| C08-typescript6-release | F002 | claim adds `InfoWorld` source attribution |

This audit is intentionally stricter than the earlier human-role blind review. It asks whether every material claim token is attributable to the exact quoted span, not merely whether source metadata makes the statement reasonable.

## Expected conservative rewrite pattern

The repair stage should keep the supported proposition and drop only quote-external context. Examples:

- `NASA 将此次试飞...` → `此次试飞的目标发射时间不早于 4 月 1 日（星期三）。`
- `Gracenote 虚拟奖牌榜预测美国获得 39 枚金牌。` → `Virtual Medal Table 列出美国 39 枚金牌。`
- `在 PEP 719 的该固定提交中，3.13.0 candidate 2...` → `3.13.0 candidate 2 被列为 2024-09-06（星期五）。`
- `FAA ... 2025 年 1 月 16 日...` → `FAA 要求 SpaceX 就 1 月 16 日发射操作中的 Starship 损失开展事故调查。`

Source provenance remains available in citation metadata and can still be described in `limitation` / `summary`; it is simply no longer allowed to masquerade as content of the quote.

## Regression coverage

Regression tests cover:

- all observed boundary-leak classes above;
- translated English month names;
- repair feedback causing a second Agent 2 attempt;
- the fixed classroom demo, whose findings were also rewritten to stay inside their exact quotes.

## Interpretation

This refinement does **not** claim a new post-fix semantic precision number until the live/frozen model suite is rerun. What is established deterministically is that the nine known metadata/date leakage patterns can no longer silently enter a validated `EvidenceFinding`; they must be repaired or excluded.
