# adaptorch-mcp

Installable Python wrapper for the AdaptOrch MCP server.

The package runs a hardened facade over `adaptorch.mcp_server`, so routing and synthesis stay aligned with AdaptOrch core without copying those algorithms into the wrapper. The default `remote` exposure profile keeps local topology and trace oracles out of the public MCP surface.

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

Use stdio for Claude Code, Claude Desktop, and other local MCP hosts. The upstream token is the AdaptOrch API key issued at `https://adaptorch.com/app/api-keys` (`ado_live_*`, or `ado_test_*` for test mode; legacy `ak_*` keys remain accepted).

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<ado_live_your-key>"
adaptorch-mcp --transport stdio --base-url https://adaptorch.com
```

Runs submitted through this wrapper are stamped `metadata.connector_source="mcp"` by the engine, so they appear in the dashboard MCP status card and `https://adaptorch.com/app/runs` for the key's tenant.

## Run HTTP MCP

Use HTTP for local gateways, reverse proxies, or remote MCP clients. Keep the client-facing MCP token separate from the upstream AdaptOrch token.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<upstream-adaptorch-token>"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<client-facing-mcp-token>"  # must differ from upstream

adaptorch-mcp \
  --transport http \
  --base-url https://adaptorch.com \
  --http-host 127.0.0.1 \
  --http-port 8765 \
  --http-auth-token "$ADAPTORCH_MCP_HTTP_AUTH_TOKEN"
```

Health and metrics require the client-facing bearer token:

```bash
python - <<'PY'
import os
from urllib.request import Request, urlopen

request = Request(
    "http://127.0.0.1:8765/mcp/health",
    headers={"Authorization": f"Bearer {os.environ['ADAPTORCH_MCP_HTTP_AUTH_TOKEN']}"},
)
with urlopen(request) as response:
    print(response.read().decode("utf-8"))
PY
```

The built-in HTTP listener is loopback-only. Put an authenticated TLS reverse proxy in front of it for remote clients.

## CLI reference

| Command | Purpose | Important options |
| --- | --- | --- |
| `adaptorch-mcp` | Start the stdio or HTTP MCP server. | `--transport stdio|http`, `--base-url`, `--api-token`, `--timeout-seconds`, `--stdio-framing`, `--http-host`, `--http-port`, `--http-auth-token` |
| `adaptorch-mcp-doctor` | Print redacted local diagnostics. | `--json`, `--strict` |
| `adaptorch-mcp-smoke` | Verify stdio `initialize` + `tools/list`. | `--command`, `--base-url`, `--api-token`, `--timeout-seconds`, repeatable `--expected-tool` |

For `adaptorch-mcp`, the public wrapper resolves the control-plane URL in this order: explicit `--base-url`, then trimmed/validated `ADAPTORCH_CONTROL_PLANE_BASE_URL`, then the hosted fallback `https://adaptorch.com`. `adaptorch-mcp-smoke` keeps a local-dev fallback of `http://127.0.0.1:8000` when no base URL is configured. Pass `--base-url` explicitly in checked-in MCP client configs for reproducible behavior.

## Environment variables

| Variable | Purpose | Notes |
| --- | --- | --- |
| `ADAPTORCH_CONTROL_PLANE_TOKEN` | Upstream AdaptOrch API key (`ado_live_*`/`ado_test_*`, legacy `ak_*`) from `/app/api-keys`. | Required unless `--api-token` is passed. |
| `ADAPTORCH_CONTROL_PLANE_BASE_URL` | Base URL used when `--base-url` is omitted. | Trimmed and validated as HTTP(S); do not embed credentials. |
| `ADAPTORCH_MCP_HTTP_AUTH_TOKEN` | Client-facing bearer token for HTTP/SSE MCP. | Required for HTTP and must differ from the upstream token. |
| `ADAPTORCH_MCP_EXPOSURE_PROFILE` | MCP exposure policy. | `remote` (default) hides local route/trace oracles; `full` explicitly restores the parent surface. |
| `ADAPTORCH_MCP_ALLOW_INSECURE_CONTROL_PLANE` | Development-only remote HTTP opt-in. | Truthy values allow plaintext non-loopback control-plane URLs; never enable in production. |
| `ADAPTORCH_MCP_ALLOWED_ORIGINS` | Comma-separated HTTP origin allowlist. | Use with browser or remote HTTP clients. |
| `ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES` | Maximum accepted HTTP request body size. | Keep bounded for public deployments. |
| `ADAPTORCH_MCP_REQUEST_TIMEOUT_SECONDS` | HTTP request timeout budget. | Applies to HTTP server request handling. |
| `ADAPTORCH_MCP_MAX_SSE_SUBSCRIBERS` | Maximum concurrent SSE subscribers. | Defaults are provided by `adaptorch.mcp_server`. |
| `ADAPTORCH_MCP_TIMEOUT_SECONDS` | Control-plane client timeout for app-factory usage. | Useful when embedding the ASGI app. |
| `ADAPTORCH_MCP_HTTP_HOST` / `ADAPTORCH_MCP_HTTP_PORT` | Shell/template values for `--http-host` and `--http-port`. | CLI flags are authoritative. |
| `ADAPTORCH_REPRODUCIBLE` | Benchmark/eval reproducibility beta. | Benchmark/eval scope only; not general runtime determinism. |
| `ADAPTORCH_ROUTER_ACCURACY_GATE` | Online-router learned-model gate. | `point` default or `wilson`; advanced/operator use. |
| `ADAPTORCH_PAPER_SEMANTIC_WEIGHT` | Paper-mode lexical/semantic blend. | Default `0.35`; nonzero values use Python scoring over the native fast path. |

## Engine-delegated optional controls

The wrapper forwards these controls to the installed `adaptorch` engine; it does
not implement routing, synthesis, or benchmark algorithms itself. See the root
configuration guide for non-env controls such as `manifest_canonical_sha256`,
`pass_rate_credit`, `quality_signal`, `prefer_multi_model_ensemble_singleton`,
and MCP `prefer_ensemble_singleton`.

## Tool surface

| Tool | Purpose |
| --- | --- |
| `adaptorch_run` | Submit an AdaptOrch task payload and optionally wait. |
| `adaptorch_get_run` | Read run summary by `run_id`. |
| `adaptorch_get_artifacts` | Read artifact metadata for a run. |
| `adaptorch_list_runs` | List recent runs. |
| `adaptorch_cancel_run` | Request run cancellation (write/destructive; keep manually approved). |
| `adaptorch_server_metrics` | Read redacted MCP server metrics. |
| `adaptorch_capabilities` | Read synthesis modes, connectors, and server features. |
| `adaptorch_plan_catalog` | Read hosted plan catalog: Starter `$0`, Pro `$39`, Team `$149`. |

`adaptorch_get_traces` and `adaptorch_route_topology` are available only when `ADAPTORCH_MCP_EXPOSURE_PROFILE=full`. In the default profile, run diagnostics and telemetry are redacted, run-resource templates are hidden, completions are disabled, and server events are not broadcast to SSE subscribers.

## Security boundary

The hardened defaults reduce direct algorithm-oracle, transport, and token-confusion risk. They do not provide DRM: reverse engineering cannot be made impossible for distributed Python code or a queryable black-box service. Keep proprietary algorithms and rate-limit/model-extraction defenses on the hosted control plane; treat `full` as trusted local/operator mode only.

Remote control-plane URLs require HTTPS by default. Plain HTTP is accepted only for exact loopback addresses, unless the development-only `ADAPTORCH_MCP_ALLOW_INSECURE_CONTROL_PLANE=1` opt-in is set. The HTTP MCP listener itself accepts only loopback binds.

## Diagnostics and smoke tests

```bash
adaptorch-mcp-doctor
adaptorch-mcp-doctor --json
adaptorch-mcp-doctor --strict
```

The doctor command reports package availability, expected MCP tools, redacted environment metadata, and `controlPlane` base-url plus transport-policy validity without printing token values. The control-plane token entry adds `formatRecognized` (prefix check against the dashboard `ado_*`/`ak_*` key contract, booleans only). `--strict` fails for invalid exposure profiles, malformed URLs, or remote plaintext URLs without the explicit development opt-in.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<ado_live_your-key>"
adaptorch-mcp-smoke --base-url https://adaptorch.com
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
export ADAPTORCH_CONTROL_PLANE_BASE_URL="https://adaptorch.com"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<client-facing-mcp-token>"  # distinct from upstream
```

```python
from adaptorch_mcp import create_default_mcp_http_app

app = create_default_mcp_http_app()
```
