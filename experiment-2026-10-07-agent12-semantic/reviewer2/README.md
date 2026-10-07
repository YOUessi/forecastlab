# Agent 2 second-reviewer blind audit

## Purpose

The existing Agent 2 after audit has one reviewer. This directory provides a genuinely blind second-review workflow so inter-rater agreement can be reported without treating an LLM or the first reviewer as an independent human.

Blind packet:

`agent2-after-blind-review.json`

It contains the same 30 seeded findings used by the after audit, but all first-reviewer labels and notes are stripped.

## Reviewer rubric

For each row, fill `human_label` with exactly one of:

- `supported`: the material claim is directly entailed by the cited exact quote(s);
- `partially_supported`: the quote supports the core point but the claim adds a material detail/context not directly present;
- `unsupported`: the quote does not support the material claim or supports a materially different proposition;
- `unclear`: the sample is too ambiguous to judge reliably.

Fill `human_notes` with a brief reason. Do not use outside knowledge or source metadata to rescue unsupported claim content.

## Agreement scoring

After reviewer 2 finishes, save the completed file separately, then run:

```bash
uv run python eval/score_interrater.py \
  experiment-2026-10-07-agent12-semantic/results/agent2-audit-labeled-after.json \
  experiment-2026-10-07-agent12-semantic/reviewer2/agent2-after-reviewer2-labeled.json \
  --output experiment-2026-10-07-agent12-semantic/results/agent2-interrater-after.json
```

The scorer reports:

- exact raw agreement;
- four-class Cohen's kappa;
- strict-support binary kappa (`supported` vs all other labels);
- lenient-support binary kappa (`supported + partially_supported` vs the rest; may be undefined when both reviewers put every item in the positive class);
- confusion matrix;
- all disagreements for adjudication.

## Independence requirement

Reviewer 2 must be a second human who has not seen reviewer 1's labels before completing the blind packet. ChatGPT or another model must not be reported as the second human reviewer.
