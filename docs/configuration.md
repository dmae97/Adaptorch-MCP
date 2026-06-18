# Configuration

`adaptorch-mcp` delegates to `adaptorch.mcp_server`, so the same runtime flags and environment variables apply.

## Required Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `ADAPTORCH_CONTROL_PLANE_TOKEN` | yes unless `--api-token` is passed | Upstream AdaptOrch bearer token or cloud API key |
| `ADAPTORCH_CONTROL_PLANE_BASE_URL` | no | Default control-plane/gateway base URL for wrappers |
| `ADAPTORCH_MCP_HTTP_AUTH_TOKEN` | HTTP only | Client-facing bearer token for MCP HTTP/SSE |

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
adaptorch-mcp --transport http --http-host 127.0.0.1 --http-port 8765
```

Clients must call `/mcp` or `/mcp/sse` with:

```text
Authorization: Bearer <mcp-client-token>
```

## Diagnostics

```bash
adaptorch-mcp-doctor
adaptorch-mcp-doctor --json
```

`adaptorch-mcp-doctor` is safe to paste into support tickets: token values are redacted and only set/length metadata is shown.

## stdio Smoke Test

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.ai.kr
```

The command starts `adaptorch-mcp --transport stdio`, sends `initialize` and `tools/list`, then verifies the expected core tool names.

## Public Plan Catalog

AdaptOrch MCP exposes the hosted cloud plan catalog via:

- Tool: `adaptorch_plan_catalog`
- Resource: `adaptorch://plans/cloud`
- Capability field: `cloud_plan_catalog`

Current catalog: Starter `$0`, Pro `$39`, Team `$149`.
