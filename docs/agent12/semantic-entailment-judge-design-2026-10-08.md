# Agent 2 semantic entailment judge design — 2026-10-08

## 1. Motivation

Agent 2 now has two deterministic trust layers:

1. exact-quote structural validation: evidence ID, snapshot hash, paragraph, verbatim quote and offsets;
2. exact-quote boundary validation: dates/numbers, metadata leakage, named entities and selected semantic/provenance cues.

Boundary v2 reached 90.0% strict support under the stricter simulated Reviewer 2, with 100% lenient support and no unsupported/unclear rows. The remaining errors are fine-grained semantic entailment questions such as unresolved pronouns, grammatical-role shifts and contextual paraphrase.

Adding more case-specific regex rules would overfit the current 30-row audit. The next layer should therefore be a general semantic entailment judge.

## 2. Proposed pipeline

```text
Finding candidate
  ↓
Exact quote structural validator
  ↓ fail → repair/reject
Boundary validator
  ↓ fail → repair/reject
Semantic entailment judge
  ↓
entailed + calibrated confidence → accept
partial / not entailed / unclear → repair or quarantine
low-confidence entailed → review/quarantine
```

The semantic judge sees only:
- `claim`
- exact quote(s)

It must not see publisher, source title, URL, question answer, other reviewer labels or outside knowledge.

## 3. Judge outputs

Four labels:
- `entailed`
- `partially_entailed`
- `not_entailed`
- `unclear`

Plus:
- confidence in [0,1];
- unsupported claim spans;
- short rationale.

The output label is not trusted blindly. It is calibrated against the human-role exact-quote audit.

## 4. Calibration objective

The main production metric is **precision of accepted findings**:

`human-supported accepted / all judge-accepted`

This corresponds to the strict-support rate users actually see after the gate.

Secondary metrics:
- supported recall: how many genuinely supported findings survive;
- non-strict specificity: how many partial/unsupported/unclear findings are blocked;
- gate coverage / acceptance rate;
- four-class exact agreement.

Thresholds are evaluated at 0.50 / 0.70 / 0.80 / 0.90 / 0.95.

A candidate production threshold should target:
- accept precision ≥ 0.95 first, preferably ≥ 0.98 on a larger set;
- zero or near-zero false accepts among unsupported findings;
- supported recall preferably ≥ 0.90;
- no silent fallback if the judge fails.

The current 30-row sample is sufficient for bootstrap calibration but **not** enough to make a statistically strong 98% reliability claim. Before claiming 98%, expand to at least roughly 100–200 diverse labelled findings.

## 5. Independence

A same-model judge is useful only for bootstrap diagnostics.

Final evaluation should prefer a different judge model/provider from the Agent 2 generator. LLM judges can exhibit self-preference/family preference, so a model should not be treated as independent merely because it is invoked with a different prompt.

The harness therefore:
- prefers `ENTAILMENT_JUDGE_API_KEY / BASE_URL / MODEL`;
- refuses implicit fallback to the primary generation model;
- requires explicit `--allow-primary-model` for same-model bootstrap runs;
- records whether the judge is independent.

## 6. LLM judge vs NLI

### LLM judge — primary next experiment

Advantages:
- handles Chinese claims against English quotes directly;
- can reason about pronouns, grammatical roles and conservative paraphrase;
- can return unsupported spans and explanations.

Risks:
- self/family bias;
- prompt sensitivity;
- extra API latency/cost;
- confidence values are not calibrated probabilities.

### Multilingual NLI — independent baseline

A multilingual NLI cross-encoder is attractive as a cheap deterministic baseline. It should be evaluated offline before adding a runtime dependency.

Important constraints for ForecastLab:
- many pairs are cross-lingual (Chinese claim, English quote);
- the distinction between full entailment and partial entailment is finer than classic entailment/neutral/contradiction;
- a small NLI model may be useful as a second opinion or cascade, not necessarily as the sole production gate.

Recommended research comparison:

```text
Boundary-v2 only
vs
Boundary-v2 + independent LLM judge
vs
Boundary-v2 + multilingual NLI
vs
Boundary-v2 + NLI then LLM judge on uncertain rows
```

## 7. Rollout stages

1. **audit-only** — implemented first; never changes production findings.
2. **shadow mode** — run judge on production findings and log decisions, but do not block.
3. **soft gate** — non-entailed decisions trigger one conservative rewrite; still record both before/after.
4. **hard gate** — only after calibration on a larger held-out labelled set.

## 8. Why not enable the hard gate now

The present human-role v2 audit has only three non-strict rows in 30. With such a small negative class, a judge can look excellent by chance and specificity estimates are unstable.

The correct next claim is therefore:

> We implemented a general quote-only entailment judge and calibrated it against the existing human-role audit.

Only after an expanded held-out audit should the project claim that the semantic judge raises production strict support to 95% or 98%.
