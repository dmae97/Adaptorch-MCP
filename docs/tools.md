# MCP Tool Surface

The package delegates tool registration to `adaptorch.mcp_server`. The public wrapper expects the following core tools when paired with a recent AdaptOrch release.

| Tool | Type | Purpose |
| --- | --- | --- |
| `adaptorch_run` | write | Submit an AdaptOrch task payload and optionally wait for terminal status. |
| `adaptorch_get_run` | read | Fetch a run summary by `run_id`. |
| `adaptorch_get_artifacts` | read | Fetch artifact metadata for a run. |
| `adaptorch_list_runs` | read | List recent control-plane runs. |
| `adaptorch_get_traces` | read | Fetch execution traces for a run. |
| `adaptorch_cancel_run` | write | Request cancellation for an in-flight run. |
| `adaptorch_route_topology` | read/local | Route a DAG locally through AdaptOrch's topology router. |
| `adaptorch_server_metrics` | read/local | Read redacted MCP server metrics. |
| `adaptorch_capabilities` | read/local | Read synthesis modes, connectors, server features, and plan catalog. |
| `adaptorch_plan_catalog` | read/local | Read hosted plan catalog: Starter $0, Pro $39, Team $149. |

## Resources

| Resource | Purpose |
| --- | --- |
| `adaptorch://tools` | Tool registry summary. |
| `adaptorch://connectors` | Available connector names. |
| `adaptorch://server-info` | Protocol and server metadata. |
| `adaptorch://plans/cloud` | Hosted cloud plan catalog. |
| `adaptorch://runs/{run_id}/summary` | Run summary resource template. |
| `adaptorch://runs/{run_id}/artifacts` | Run artifacts resource template. |

## Public Verification

Use the smoke command after installation:

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.ai.kr
```

The smoke command checks `initialize`, `tools/list`, and the expected core tool subset without printing token values. Add repeatable `--expected-tool <name>` flags when validating a specific hosted/core release.

## Auto-approve guidance

For trusted local clients, auto-approve only tools whose outputs are safe for that client. Keep `adaptorch_run` and `adaptorch_cancel_run` manually approved. For shared or production clients, avoid auto-approving run, artifact, and trace readers unless those payloads are already sanitized.
