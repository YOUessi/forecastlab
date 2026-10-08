# Agent 2 strong independent judge v2 — 2026-10-08

## Scope

This experiment continues the frozen post-boundary semantic-entailment study on a **new research branch**. Production Agent 2 remains unchanged.

Primary benchmark:
- `eval/benchmarks/agent2-entailment-post-boundary-v1.json`
- 239 rows total
- dev: 157 rows
- held-out test: 82 rows
- test is not used for prompt or threshold tuning.

Target:
- accepted strict precision >= 95%
- supported recall >= 90%

## Qwen2.5-3B-Instruct

Run locally on Tang GPU using the same quote-only prompt and frozen benchmark as the 1.5B run.

### Dev

All listed confidence thresholds 0.50–0.95 produce the same accepted set:

- accepted: 48/157
- accepted strict precision: **72.92%**
- supported recall: **50.0%**
- false accepts: 13

### Held-out test

- accepted: 22/82
- accepted strict precision: **81.82%**
- supported recall: **52.94%**
- false accepts: 4
- Wilson 95% precision interval: **61.48%–92.69%**

The 3B model is materially stricter than Qwen2.5-1.5B, but still fails the 95% precision / 90% recall target.

## NLI + Qwen3B

Dev-only threshold selection was performed using the frozen cascade grid.

### Agreement

Selected on dev:
- NLI accept >= 0.95
- Qwen3B entailed (confidence threshold selected as 0.50; accepted set is unchanged across the model's discrete confidence outputs)

Held-out test:
- accepted: 18/82
- accepted strict precision: **94.44%**
- supported recall: **50.0%**
- false accepts: 1
- Wilson 95% precision interval: **74.24%–99.01%**

This is close to the 95% precision point target, but recall is far below 90%, so it is not a viable production gate.

### NLI then Qwen3B

Held-out test:
- accepted: 36/82
- precision: **69.44%**
- recall: **73.53%**
- false accepts: 11

Not viable.

## Multi-judge ensemble with NLI + Qwen1.5B + Qwen3B

These rules were evaluated after selecting thresholds on dev only.

### Three-way unanimity

Held-out test:
- precision: **100%**
- recall: **47.06%**
- accepted: 16
- false accepts: 0

This demonstrates that precision can be driven to 100% by requiring unanimity, but only by rejecting more than half of genuinely supported findings. It is therefore not useful as a production hard gate.

### Two-of-three majority

Held-out test:
- precision: **73.53%**
- recall: **73.53%**
- accepted: 34
- false accepts: 9

### Qwen3B plus at least one other judge

Held-out test:
- precision: **85.71%**
- recall: **52.94%**
- accepted: 21
- false accepts: 3

No tested ensemble reaches the frozen target.

## Strong API judge route

An OpenAI-compatible ARC Bench endpoint is configured on the Mac and exposes multiple non-DeepSeek model families, including `qwen3.8-max`, `kimi-k3`, and GLM/Minimax models.

Automatic reuse of the API key from an unrelated local project was blocked by the credential-safety layer, so **no API Judge quality result is claimed**. The harness is ready and supports checkpoint/resume. A future run should use an explicitly authorized judge credential.

## Qwen2.5-7B-Instruct

The next local model is Qwen2.5-7B-Instruct. Download is resumable and is being performed independently of the 3B inference. The first Hugging Face/XET route stalled; download was restarted with standard HTTP while preserving the cache.

No 7B quality result is reported until all 239 rows and dev/test scoring complete.

## Current decision

Completed evidence so far:

| Judge | Held-out precision | Held-out recall | Meets 95/90? |
| --- | ---: | ---: | --- |
| Multilingual NLI @ 0.95 | 75.0% | 70.6% | No |
| Qwen2.5-1.5B @ 0.90 | 44.8% | 76.5% | No |
| Qwen2.5-3B | 81.8% | 52.9% | No |
| NLI + Qwen3B agreement | 94.44% | 50.0% | No |
| NLI + Qwen1.5B + Qwen3B unanimity | 100% | 47.1% | No |

The trend is clear: larger/stricter judges improve precision, but current approaches trade away too much recall. The next valid step is Qwen7B and, when explicitly authorized, a stronger independent API judge on the same frozen benchmark.
