# Configuration

`adaptorch-mcp` delegates to `adaptorch.mcp_server`, so the canonical MCP flags, tools, resources, prompts, safety checks, and transports come from the installed AdaptOrch core release.

## Required Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `ADAPTORCH_CONTROL_PLANE_TOKEN` | yes unless `--api-token` is passed | Upstream AdaptOrch bearer token or cloud API key |
| `ADAPTORCH_CONTROL_PLANE_BASE_URL` | no | Base URL used when `--base-url` is omitted; surrounding whitespace is ignored and non-empty values must be HTTP(S) URLs with a host |
| `ADAPTORCH_MCP_HTTP_AUTH_TOKEN` | HTTP only | Client-facing bearer token for MCP HTTP/SSE |

Base-url resolution differs by entrypoint:

| Entrypoint | Resolution when `--base-url` is omitted | Default with no env |
| --- | --- | --- |
| `adaptorch-mcp` | `ADAPTORCH_CONTROL_PLANE_BASE_URL` after trimming/validation, then hosted fallback | `https://adaptorch.com` |
| `adaptorch-mcp-smoke` | `ADAPTORCH_CONTROL_PLANE_BASE_URL`, then local smoke target | `http://127.0.0.1:8000` |
| `create_default_mcp_http_app()` | Delegates to the AdaptOrch engine and reads environment only | engine default |

Pass `--base-url` explicitly in checked-in MCP client configs for reproducible behavior. Do not embed credentials in base URLs; use token environment variables instead.

The connector always sends `ADAPTORCH_CONTROL_PLANE_TOKEN` as `Authorization: Bearer <token>`. Hosted AdaptOrch SaaS (`https://adaptorch.com`) resolves `ado_live_*`/`ado_test_*` (legacy `ak_*`) API keys from that bearer header, so dashboard-issued keys work unchanged; the hosted API additionally accepts `X-API-Key` from other client types. Local and custom control planes receive the same bearer header.

## HTTP Environment

| Variable | Purpose |
| --- | --- |
| `ADAPTORCH_MCP_ALLOWED_ORIGINS` | Comma-separated allowed origins for HTTP/SSE clients. |
| `ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES` | Maximum accepted HTTP request body size. |
| `ADAPTORCH_MCP_REQUEST_TIMEOUT_SECONDS` | HTTP request timeout budget. |
| `ADAPTORCH_MCP_MAX_SSE_SUBSCRIBERS` | Maximum concurrent SSE subscribers. |
| `ADAPTORCH_MCP_TIMEOUT_SECONDS` | Control-plane client timeout for embedded/app-factory usage. |
| `ADAPTORCH_MCP_HTTP_HOST` / `ADAPTORCH_MCP_HTTP_PORT` | Shell/template values for `--http-host` and `--http-port`; CLI flags are authoritative. |

## Engine-delegated optional algorithm controls (latest)

`adaptorch-mcp` forwards these controls to the installed `adaptorch` engine. The
wrapper does not implement routing, synthesis, quality scoring, or benchmark
algorithms itself.

### Environment controls

| Variable | Scope | Notes |
| --- | --- | --- |
| `ADAPTORCH_REPRODUCIBLE` | Benchmark/eval beta | Fixes benchmark clock/RNG sources and canonicalizes record timing/path fields. It does not cover live-provider outputs, parallel-suite record order, cassettes, traces, or report timing aggregates. |
| `ADAPTORCH_ROUTER_ACCURACY_GATE` | Online router | `point` is the default; `wilson` compares learned-router adoption against a Wilson lower bound. Advanced/operator use. |
| `ADAPTORCH_PAPER_SEMANTIC_WEIGHT` | Synthesis | Default is `0.35`. Nonzero semantic weight, plus CJK/Hangul inputs, use Python scoring rather than the native fast path. |

### Engine API/config controls

| Control | Scope | Notes |
| --- | --- | --- |
| `manifest_canonical_sha256` | Benchmark manifest | Importable as `adaptorch.benchmarking.manifest_canonical_sha256`; hashes canonical nonvolatile manifest fields. |
| `pass_rate_credit` | Quality signal | Opt-in partial credit in `adaptorch.quality_signal.compute_quality`; do not claim it changes `AdaptOrchEngine` router feedback by default. |
| `quality_signal` | Online-router learning | Exact-answer tokens are compared before fuzzy gold-label matching. |
| `prefer_multi_model_ensemble_singleton` | Routing threshold | Auto-enables when at least two ensemble providers exist and synthesis mode is not `direct`, unless an explicit debate-singleton preference wins. |
| `prefer_ensemble_singleton` | MCP run hint | Manual hint forwarded by MCP/benchmark run options. |
| Online-router knobs | Operator tuning | `retrain_window`, `min_loo_accuracy`, `min_posterior`, `quality_floor`, `use_quality_weights`, `use_failure_evidence`, `exploration_rate`, `max_observations`, `cv`, and `kfold_k`. |

## Common Flags

```bash
adaptorch-mcp --help
```

Important flags:

- `--transport stdio|http`
- `--base-url <url>`
- `--api-token <token>`
- `--timeout-seconds <float>`
- `--stdio-framing newline|content-length`
- `--http-host <host>`
- `--http-port <port>`
- `--http-auth-token <token>`

## Local stdio

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp --transport stdio --base-url http://127.0.0.1:8000
```

## Production stdio

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<tenant-api-key>"
adaptorch-mcp --transport stdio --base-url https://adaptorch.com
```

## Local HTTP

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<upstream-token>"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<mcp-client-token>"
adaptorch-mcp \
  --transport http \
  --base-url https://adaptorch.com \
  --http-host 127.0.0.1 \
  --http-port 8765 \
  --http-auth-token "$ADAPTORCH_MCP_HTTP_AUTH_TOKEN"
```

Clients must call `/mcp` or `/mcp/sse` with:

```text
Authorization: Bearer <mcp-client-token>
```

## Diagnostics

```bash
adaptorch-mcp-doctor
adaptorch-mcp-doctor --json
adaptorch-mcp-doctor --strict
```

`adaptorch-mcp-doctor` is safe to paste into support tickets: token values are redacted and only set/length metadata is shown. JSON output includes a `controlPlane` block with the default URL, redacted environment URL, resolved URL, source (`env` or `hosted-default`), and invalid-env status.

## stdio Smoke Test

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.com
```

The command starts `adaptorch-mcp --transport stdio`, sends `initialize` and `tools/list`, then verifies the expected core tool subset. When neither `--base-url` nor `ADAPTORCH_CONTROL_PLANE_BASE_URL` is set, smoke intentionally targets `http://127.0.0.1:8000` for local development. Add repeatable `--expected-tool <name>` flags when validating a specific hosted/core release.

## Public Plan Catalog

AdaptOrch MCP exposes the hosted cloud plan catalog via:

- Tool: `adaptorch_plan_catalog`
- Resource: `adaptorch://plans/cloud`
- Capability field: `cloud_plan_catalog`

Current catalog: Starter `$0`, Pro `$39`, Team `$149`.
