# Agent 1/2 semantic robustness baseline — 2026-10-07

## Scope

This experiment evaluates Agent 1 neutral-vs-leading robustness and Agent 2 semantic support from exact quotes to findings. Model: DeepSeek `deepseek-flash`, temperature 0.

## Agent 1 — real ForecastLab-v2 paired set

Eight neutral/leading pairs were run twice (32 framing runs).

| Metric | Result |
| --- | ---: |
| Runs succeeded | 32/32 |
| Leading premise anchor detected | 100% |
| Explicit fields preserved | 100% |
| Neutral runs containing at least one premise | 81.25% |
| Runs with blocking clarification | 75% |
| Ready for confirmation | 25% |
| Leading member has more premises than neutral | 43.75% |

Inspection shows many neutral premises are not world-state assumptions but restatements of the research object, resolution criterion, time cutoff, comparison dates, or binary-decision wording.

## Agent 1 — fictional sanity set

A second eight-pair suite removes dependence on real historical facts and adds exactly one explicit antecedent only in the leading member. It was also run twice.

| Metric | Result |
| --- | ---: |
| Runs succeeded | 32/32 |
| Leading premise anchor detected | 100% |
| Explicit fields preserved | 100% |
| Neutral runs containing at least one premise | 81.25% |
| Runs with blocking clarification | 100% |
| Ready for confirmation | 0% |
| Leading member has more premises than neutral | 56.25% |

The same neutral-premise rate confirms a real semantic-boundary problem: Agent 1 frequently serializes question scope/identity/time/resolution fields as premises. Blocking clarifications are also over-produced, often reopening fields already supplied by `resolve_by`, `resolution_rule`, or `resolution_source`.

## Agent 2 — finding to exact-quote semantic audit

Agent 2 was run directly on all 24 ForecastLab-v2 evidence packs. It produced 50 structurally validated findings. Seed 7606 selected 30 findings for a single-reviewer semantic audit.

| Label | Count |
| --- | ---: |
| supported | 15 |
| partially_supported | 15 |
| unsupported | 0 |
| unclear | 0 |

Strict support rate: **50%**. Lenient support rate (supported + partial): **100%**.

Common partial-support patterns include: turning a draw announcement into a team-specific path claim; turning `late 2024` into support for an October window; converting planned availability into a stronger no-delivery statement; and inferring non-release from a roadmap/title that only says `plans`.

## Conclusions

- Agent 1 preserves explicit user-owned fields and detects explicit leading premises, but its premise boundary is too broad and its clarification policy too aggressive.
- Agent 2 structural provenance is effective at preventing unrelated/fabricated quotes in this sample, but exact-quote existence is not enough to guarantee semantic entailment.
- The next repair should narrow Agent 1 premises to falsifiable world-state/causal assumptions and require Agent 2 finding claims to be conservative paraphrases entailed by their cited text.

## Limitations

- Agent 1 leading detection uses frozen lexical anchors, not a complete expert gold annotation of every possible hidden assumption.
- The neutral-premise metric is diagnostic: not every neutral extracted premise is necessarily harmful.
- Agent 2 has one human reviewer; inter-rater reliability is not available.
- The 30 findings are a seeded sample from one model run.
- Temperature 0 does not guarantee deterministic remote-model output.
