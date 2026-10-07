# Simulated second-review dry run — 2026-10-08

This file verifies the **workflow**, not human inter-rater reliability.

- Source packet: `reviewer2/agent2-after-blind-review.json`
- Simulated reviewer output: `reviewer2/agent2-after-simulated-review.json`
- Comparison output: `results/agent2-interrater-simulated-after.json`
- Samples: 30
- Simulated reviewer counts: 23 supported, 7 partially_supported
- Raw agreement with reviewer 1: 86.67%
- Four-class Cohen's kappa: 0.534884
- Strict-support binary kappa: 0.534884
- Lenient-support kappa: undefined because both reviewers place all rows in the lenient-positive class.

The four disagreements are all boundary cases where the exact quote supports the core factual content but some provenance/date/institution context is supplied outside the quote.

**Do not report these metrics as a second human review.** The real independent-human reviewer remains pending. This dry run exists so the blind-packet format, scoring semantics, repository traceability, PR, and CI flow can be exercised end to end.
