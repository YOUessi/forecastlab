# Moore Threads vLLM-MT integration

This document records the ForecastLab inference-backend integration for the course Moore Threads GPU bonus path. It is based on the course-provided **vLLM-MT 大模型推理服务文档 V2.2 (2026-09-30)**. Reference numbers from that document are **not** ForecastLab experimental results.

## 1. Scope

ForecastLab keeps Agent 1–7 unchanged above the model transport layer:

```text
React / FastAPI / LangGraph
          ↓
      ModelClient
       ↙   ↓    ↘
    Qwen DeepSeek vLLM-MT
```

The `vllm_mt` provider only changes the OpenAI-compatible endpoint, model name, timeout, and provider-specific request options.

## 2. Source document notes

The supplied vLLM-MT V2.2 document describes vLLM-MT as Moore Threads' adaptation of community vLLM with MUSA GPU-specific optimization and links the source repository at `https://gitee.com/MooreThreads/vLLM-MT`.

The document recommends:

- software stack 4.3.5 for the current S4000 setup, with `mt-container-toolkit 2.2.0`;
- a newer 5.2.0 image path using torch_musa 2.11 and vLLM 0.29.1;
- `vllm serve` for model serving;
- `vllm-perf` and `vllm_L0_regression_test.sh` for performance validation;
- saving benchmark logs under `/workspace/bench_log`.

Its Qwen3.6-35B-A3B example uses four S4000 GPUs with tensor parallel size 4, port 18014, Flash Attention, MTP speculative decoding and graph/compile settings. The document's reported throughput numbers are reference values only and must not be copied into the ForecastLab result section as measured data.

## 3. ForecastLab configuration

Copy `.env.example` to `.env` and select the provider:

```bash
FORECASTLAB_MODEL_PROVIDER=vllm_mt
VLLM_MT_BASE_URL=http://127.0.0.1:18014/v1
VLLM_MT_MODEL=Model
VLLM_MT_TIMEOUT=180
```

A real API key is not required for the default local vLLM server. If authentication is enabled in a custom deployment, set `VLLM_MT_API_KEY`.

Cloud behavior remains compatible:

```bash
FORECASTLAB_MODEL_PROVIDER=auto
QWEN_API_KEY=...
# or
DEEPSEEK_API_KEY=...
```

In `auto`, Qwen retains the previous precedence when its key exists; otherwise DeepSeek is selected.

## 4. Recommended network layout

The source document's serving example binds to `127.0.0.1:18014`. Keep that local binding on the GPU server.

When ForecastLab runs on another machine, use an SSH tunnel instead of opening the inference port publicly:

```bash
ssh -L 18014:127.0.0.1:18014 USER@S4000_HOST
```

Then ForecastLab still uses:

```text
http://127.0.0.1:18014/v1
```

This avoids exposing an unauthenticated OpenAI-compatible inference endpoint to the network.

## 5. Deployment check

After the vLLM-MT container and model server are running:

```bash
uv run python eval/model_backend_smoke.py \
  --provider vllm_mt
```

The smoke command checks:

1. `GET /v1/models`;
2. one chat completion;
3. returned model name;
4. prompt/completion token usage when supplied by the server.

It never prints an API key.

## 6. Inference performance benchmark

Representative ForecastLab Agent 1/2 prompt shapes are stored in:

```text
examples/moorethreads/inference-cases.json
```

Run:

```bash
uv run python eval/model_backend_benchmark.py \
  --provider vllm_mt \
  --cases examples/moorethreads/inference-cases.json \
  --concurrency 1 4 \
  --repeat 3 \
  --output results/moorethreads-vllm-mt.json
```

The report records per request:

- TTFT (time to first token);
- total latency;
- TPOT when usage is available;
- decode token/s;
- prompt/completion token counts;
- success/failure type.

Each concurrency batch also records aggregate total token/s and output token/s.

The script can run against the cloud baselines with the same cases:

```bash
uv run python eval/model_backend_benchmark.py \
  --provider qwen \
  --concurrency 1 4 \
  --repeat 3 \
  --output results/qwen-cloud.json
```

or:

```bash
uv run python eval/model_backend_benchmark.py \
  --provider deepseek \
  --concurrency 1 4 \
  --repeat 3 \
  --output results/deepseek-cloud.json
```

These are transport/inference measurements, not semantic-quality scores.

## 7. Agent 1/2 quality validation

Use the existing Agent 1/2 live evaluation separately:

```bash
uv run python eval/agent12.py \
  --mode live \
  --cases path/to/frozen-live-cases.json \
  --output results/agent12-live-vllm-mt.json
```

The live report now records `model_provider` and `configured_model`.

For the final report, manually review at least:

- whether Agent 1 found the intended assumptions;
- whether neutral questions received spurious assumptions;
- whether Agent 2 findings are actually supported by their cited passages;
- whether challenge evidence is substantive rather than manufactured balance;
- any invalid JSON or rejected citations.

Do not infer semantic quality from TTFT or token throughput.

## 8. Profiling and environment capture

Capture software/hardware metadata before each benchmark:

```bash
uv run python eval/collect_moorethreads_env.py \
  --output results/moorethreads-environment.json
```

On the Moore Threads host, wrap a benchmark with periodic `mthreads-gmi` sampling:

```bash
bash eval/run_with_mt_profile.sh results/mthreads-gmi.log -- \
  uv run python eval/model_backend_benchmark.py \
    --provider vllm_mt \
    --concurrency 1 4 \
    --repeat 3 \
    --output results/vllm-mt.json
```

The wrapper stores raw timestamped `mthreads-gmi` output instead of guessing a vendor-specific field layout. Report GPU utilization/memory metrics only after verifying the output columns on the actual course machine.

## 8. Suggested benchmark table

| Backend | Concurrency | Agent 1 TTFT p50 | Agent 2 TTFT p50 | TPOT p50 | output tok/s | JSON / workflow success |
|---|---:|---:|---:|---:|---:|---:|
| Qwen cloud | 1 | measured | measured | measured | measured | measured |
| vLLM-MT S4000 | 1 | measured | measured | measured | measured | measured |
| vLLM-MT S4000 | 4 | measured | measured | measured | measured | measured |

Also record:

- GPU model/count;
- Driver/MUSA/torch_musa/vLLM-MT versions;
- served model and precision;
- tensor parallel size;
- graph / compile / MTP / prefix-caching settings;
- prompt/output lengths;
- warmup count;
- number of repeated trials.

## 10. Optional vLLM-MT ablations

The V2.2 source document reports optimizations involving full/piecewise graph mode, Torch.compile, MTP stability, prefix caching, and INT8/GEMV improvements. Treat those values as vendor reference claims and rerun controlled comparisons on the course hardware.

A useful sequence is:

```text
baseline eager
→ graph
→ graph + compile
→ graph + compile + MTP
→ repeated-prefix workload with prefix caching
```

Change one factor at a time and keep model, precision, prompt lengths, concurrency and GPU count fixed.

## 11. What is implemented vs. not yet measured

Implemented in this branch:

- provider selection;
- keyless vLLM-MT endpoint support;
- provider-aware Qwen request options;
- longer local-inference timeout;
- health endpoint provider label;
- smoke test;
- streaming performance benchmark;
- Agent 1/2 representative inference cases.

Not yet measured:

- S4000/S5000 throughput on the course hardware;
- vLLM-MT Agent 1/2 semantic quality;
- vendor-reference performance reproduction;
- graph / compile / MTP ablation results.

Those fields must remain `not_run` until an actual Moore Threads endpoint is available.
