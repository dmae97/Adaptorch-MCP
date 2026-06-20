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
| `adaptorch-mcp` | `ADAPTORCH_CONTROL_PLANE_BASE_URL` after trimming/validation, then hosted fallback | `https://adaptorch.ai.kr` |
| `adaptorch-mcp-smoke` | `ADAPTORCH_CONTROL_PLANE_BASE_URL`, then local smoke target | `http://127.0.0.1:8000` |
| `create_default_mcp_http_app()` | Delegates to the AdaptOrch engine and reads environment only | engine default |

Pass `--base-url` explicitly in checked-in MCP client configs for reproducible behavior. Do not embed credentials in base URLs; use token environment variables instead.

## HTTP Environment

| Variable | Purpose |
| --- | --- |
| `ADAPTORCH_MCP_ALLOWED_ORIGINS` | Comma-separated allowed origins for HTTP/SSE clients. |
| `ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES` | Maximum accepted HTTP request body size. |
| `ADAPTORCH_MCP_REQUEST_TIMEOUT_SECONDS` | HTTP request timeout budget. |
| `ADAPTORCH_MCP_MAX_SSE_SUBSCRIBERS` | Maximum concurrent SSE subscribers. |
| `ADAPTORCH_MCP_TIMEOUT_SECONDS` | Control-plane client timeout for embedded/app-factory usage. |
| `ADAPTORCH_MCP_HTTP_HOST` / `ADAPTORCH_MCP_HTTP_PORT` | Shell/template values for `--http-host` and `--http-port`; CLI flags are authoritative. |

## Accuracy Profile Environment

Accuracy features are engine-delegated and default to `off`, preserving current behavior.

| Variable | Purpose | Values |
| --- | --- | --- |
| `ADAPTORCH_ACCURACY_PROFILE` | Named P11–P19 accuracy preset | `off` (default), `balanced`, `max_accuracy` |
| `ADAPTORCH_PARTIAL_CREDIT_PREFER_CONFIDENCE` | Prefer higher-confidence partial-credit candidates | truthy |
| `ADAPTORCH_JUDGE_OVERRIDE_MARGIN` | Confidence margin gating judge overrides | float |
| `ADAPTORCH_VERIFICATION_CRITICAL_COMMANDS` | Commands treated as verification-critical | comma list |
| `ADAPTORCH_VERIFICATION_CRITICAL_WEIGHT` | Weight applied to critical verification commands | integer or float |

Use `balanced` or `max_accuracy` only after measuring a deployment-specific improvement. Per-field overrides win over the profile.

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
adaptorch-mcp --transport stdio --base-url https://adaptorch.ai.kr
```

## Local HTTP

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<upstream-token>"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<mcp-client-token>"
adaptorch-mcp \
  --transport http \
  --base-url https://adaptorch.ai.kr \
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
adaptorch-mcp-smoke --base-url https://adaptorch.ai.kr
```

The command starts `adaptorch-mcp --transport stdio`, sends `initialize` and `tools/list`, then verifies the expected core tool subset. When neither `--base-url` nor `ADAPTORCH_CONTROL_PLANE_BASE_URL` is set, smoke intentionally targets `http://127.0.0.1:8000` for local development. Add repeatable `--expected-tool <name>` flags when validating a specific hosted/core release.

## Public Plan Catalog

AdaptOrch MCP exposes the hosted cloud plan catalog via:

- Tool: `adaptorch_plan_catalog`
- Resource: `adaptorch://plans/cloud`
- Capability field: `cloud_plan_catalog`

Current catalog: Starter `$0`, Pro `$39`, Team `$149`.
