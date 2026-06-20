# adaptorch-mcp

Installable Python wrapper for the AdaptOrch MCP server.

The package intentionally delegates runtime behavior to `adaptorch.mcp_server`, so MCP tools, transports, safety checks, and P11–P19 accuracy activation stay aligned with AdaptOrch core.

## Install

```bash
pip install adaptorch-mcp
```

If AdaptOrch is not published to your package index yet:

```bash
pip install "adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git"
pip install adaptorch-mcp
```

One-shot with `uvx`:

```bash
uvx adaptorch-mcp --help
uvx --with "adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git" adaptorch-mcp --help
```

For contributors inside this monorepo:

```bash
uv sync --all-packages --extra dev
uv run adaptorch-mcp --help
```

## Run stdio MCP

Use stdio for Claude Code, Claude Desktop, and other local MCP hosts.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp --transport stdio --base-url https://adaptorch.ai.kr
```

## Run HTTP MCP

Use HTTP for local gateways, reverse proxies, or remote MCP clients. Keep the client-facing MCP token separate from the upstream AdaptOrch token.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<upstream-adaptorch-token>"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<client-facing-mcp-token>"

adaptorch-mcp \
  --transport http \
  --base-url https://adaptorch.ai.kr \
  --http-host 127.0.0.1 \
  --http-port 8765 \
  --http-auth-token "$ADAPTORCH_MCP_HTTP_AUTH_TOKEN"
```

Health check:

```bash
python - <<'PY'
import httpx
print(httpx.get('http://127.0.0.1:8765/mcp/health').json())
PY
```

## CLI reference

| Command | Purpose | Important options |
| --- | --- | --- |
| `adaptorch-mcp` | Start the stdio or HTTP MCP server. | `--transport stdio|http`, `--base-url`, `--api-token`, `--timeout-seconds`, `--stdio-framing`, `--http-host`, `--http-port`, `--http-auth-token` |
| `adaptorch-mcp-doctor` | Print redacted local diagnostics. | `--json`, `--strict` |
| `adaptorch-mcp-smoke` | Verify stdio `initialize` + `tools/list`. | `--command`, `--base-url`, `--api-token`, `--timeout-seconds`, repeatable `--expected-tool` |

For `adaptorch-mcp`, the public wrapper resolves the control-plane URL in this order: explicit `--base-url`, then trimmed/validated `ADAPTORCH_CONTROL_PLANE_BASE_URL`, then the hosted fallback `https://adaptorch.ai.kr`. `adaptorch-mcp-smoke` keeps a local-dev fallback of `http://127.0.0.1:8000` when no base URL is configured. Pass `--base-url` explicitly in checked-in MCP client configs for reproducible behavior.

## Environment variables

| Variable | Purpose | Notes |
| --- | --- | --- |
| `ADAPTORCH_CONTROL_PLANE_TOKEN` | Upstream AdaptOrch token. | Required unless `--api-token` is passed. |
| `ADAPTORCH_CONTROL_PLANE_BASE_URL` | Base URL used when `--base-url` is omitted. | Trimmed and validated as HTTP(S); do not embed credentials. |
| `ADAPTORCH_MCP_HTTP_AUTH_TOKEN` | Client-facing bearer token for HTTP/SSE MCP. | Keep separate from the upstream token. |
| `ADAPTORCH_MCP_ALLOWED_ORIGINS` | Comma-separated HTTP origin allowlist. | Use with browser or remote HTTP clients. |
| `ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES` | Maximum accepted HTTP request body size. | Keep bounded for public deployments. |
| `ADAPTORCH_MCP_REQUEST_TIMEOUT_SECONDS` | HTTP request timeout budget. | Applies to HTTP server request handling. |
| `ADAPTORCH_MCP_MAX_SSE_SUBSCRIBERS` | Maximum concurrent SSE subscribers. | Defaults are provided by `adaptorch.mcp_server`. |
| `ADAPTORCH_MCP_TIMEOUT_SECONDS` | Control-plane client timeout for app-factory usage. | Useful when embedding the ASGI app. |
| `ADAPTORCH_MCP_HTTP_HOST` / `ADAPTORCH_MCP_HTTP_PORT` | Shell/template values for `--http-host` and `--http-port`. | CLI flags are authoritative. |
| `ADAPTORCH_ACCURACY_PROFILE` | Optional P11–P19 accuracy preset. | `off` default; `balanced` and `max_accuracy` are opt-in. |
| `ADAPTORCH_PARTIAL_CREDIT_PREFER_CONFIDENCE` | Per-field accuracy override. | Truthy value prefers higher-confidence partial-credit candidates. |
| `ADAPTORCH_JUDGE_OVERRIDE_MARGIN` | Per-field accuracy override. | Float margin for judge override gating. |
| `ADAPTORCH_VERIFICATION_CRITICAL_COMMANDS` | Per-field accuracy override. | Comma list of critical verification commands. |
| `ADAPTORCH_VERIFICATION_CRITICAL_WEIGHT` | Per-field accuracy override. | Numeric weight for critical verification commands. |

## Accuracy profile

Accuracy features are engine delegated and default to `off`, preserving current behavior. Set `ADAPTORCH_ACCURACY_PROFILE=balanced` or `max_accuracy` only after measuring a deployment-specific improvement. Per-field overrides win over the profile.

The profile surfaces the AdaptOrch core P11–P19 line: confidence-weighted and robust self-consistency, answer-aware partial credit, semantic vote pooling, medoid selection, command-criticality weighting, logprob-aware confidence, agreement-adaptive ranking, router-threshold calibration, `AccuracyProfile`, selection fusion, and measured adopt-only-if-better gates.

## Tool surface

| Tool | Purpose |
| --- | --- |
| `adaptorch_run` | Submit an AdaptOrch task payload and optionally wait. |
| `adaptorch_get_run` | Read run summary by `run_id`. |
| `adaptorch_get_artifacts` | Read artifact metadata for a run. |
| `adaptorch_list_runs` | List recent runs. |
| `adaptorch_get_traces` | Read execution traces. |
| `adaptorch_cancel_run` | Request run cancellation. |
| `adaptorch_route_topology` | Locally route a DAG through AdaptOrch's topology router. |
| `adaptorch_server_metrics` | Read redacted MCP server metrics. |
| `adaptorch_capabilities` | Read synthesis modes, connectors, and server features. |
| `adaptorch_plan_catalog` | Read hosted plan catalog: Starter `$0`, Pro `$39`, Team `$149`. |

## Diagnostics and smoke tests

```bash
adaptorch-mcp-doctor
adaptorch-mcp-doctor --json
adaptorch-mcp-doctor --strict
```

The doctor command reports package availability, expected MCP tools, redacted environment metadata, and `controlPlane` base-url resolution details without printing token values.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.ai.kr
```

Expected JSON includes `"ok": true`, `adaptorch_plan_catalog`, and the expected core tool subset. If no base URL is supplied, smoke targets `http://127.0.0.1:8000` for local development. Add repeatable `--expected-tool <name>` flags when validating a specific hosted/core release.

## Example configs

- `../../examples/claude_desktop_config.json`
- `../../examples/omk.mcp.json`
- `../../examples/mcp-http.env.example`

Checked-in examples use placeholders or environment interpolation. Fill real URLs and tokens only in local, uncommitted config files. For shared or production clients, avoid auto-approving run, artifact, and trace readers unless those payloads are already sanitized.

## HTTP app factory

`create_default_mcp_http_app()` embeds the canonical AdaptOrch MCP HTTP ASGI app. It requires an upstream control-plane token in the environment.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<upstream-adaptorch-token>"
export ADAPTORCH_CONTROL_PLANE_BASE_URL="https://adaptorch.ai.kr"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<client-facing-mcp-token>"
```

```python
from adaptorch_mcp import create_default_mcp_http_app

app = create_default_mcp_http_app()
```
