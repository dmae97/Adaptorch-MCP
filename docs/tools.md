# MCP Tool Surface

The package delegates tool registration to `adaptorch.mcp_server`. The default `remote` profile exposes nine hardened tools. The two rows marked `full only` are available only with `ADAPTORCH_MCP_EXPOSURE_PROFILE=full`.

| Tool | Type | Purpose |
| --- | --- | --- |
| `adaptorch_run` | write | Submit an AdaptOrch task payload and optionally wait for terminal status. |
| `adaptorch_get_run` | read | Fetch a run summary plus an optional bounded Correctness Wall view by `run_id`. |
| `adaptorch_get_artifacts` | read | Fetch artifact metadata for a run. |
| `adaptorch_list_runs` | read | List recent control-plane runs. |
| `adaptorch_get_traces` | read/full only | Fetch execution traces for a run. |
| `adaptorch_cancel_run` | write/destructive | Request cancellation for an in-flight run. Keep manually approved. |
| `adaptorch_route_topology` | read/local/full only | Route a DAG locally through AdaptOrch's topology router. |
| `adaptorch_server_metrics` | read/local | Read redacted MCP server metrics. |
| `adaptorch_capabilities` | read/local | Read synthesis modes, deprecated aliases, topologies, output extractors, connectors, server features, and plan catalog. |
| `adaptorch_usage` | read | Read the calling tenant's usage window: plan level, period, used, limit, remaining, percentage. |
| `adaptorch_plan_catalog` | read/local | Read hosted plan catalog: Starter $0, Pro $39, Team $149. |

## Engine algorithm surface (delegated)

The wrapper never reimplements routing or synthesis. The values below are read from the
installed `adaptorch` engine and are asserted by
`packages/adaptorch-mcp/tests/test_engine_algorithm_parity.py`.

| Surface | Engine truth | Notes |
| --- | --- | --- |
| `synthesis_mode` (supported) | `paper`, `robust`, `robust_lite`, `stable_hybrid` | Distinct strategies executed by `adaptorch.synthesis`. Default is `robust`. |
| `synthesis_mode` (serving selection) | `auto` | The control plane selects an engine mode; `synthesis_mode_requested` and `synthesis_mode_used` remain visible in run responses. Not a fifth engine algorithm. |
| `synthesis_mode` (deprecated alias) | `fourier_aggressive` → `stable_hybrid` | Still accepted for compatibility; the engine resolves it to `stable_hybrid` and reports `mode_used`. |
| `output_extractor` | `final_answer`, `multiple_choice_letter` | Engine extractor modes. `none` requests no extractor and is not forwarded to the engine. |
| Topologies | `parallel`, `sequential`, `hierarchical`, `hybrid`, `multi_model_ensemble`, `multi_turn_debate` | Router-selectable topologies reported by `adaptorch_capabilities`. |

`adaptorch_capabilities` reports `synthesis_modes` (everything callers may pass),
`supported_synthesis_modes`, `deprecated_synthesis_mode_aliases`, `topologies`, and
`output_extractor_modes`. Older engines that omit those fields still project cleanly.

## BYOK run admission

Provider credentials are process configuration, not part of the public `adaptorch_run` input schema. Set `ADAPTORCH_MCP_PROVIDER` and `ADAPTORCH_MCP_PROVIDER_MODEL` together, plus `ADAPTORCH_MCP_PROVIDER_API_KEY` for credentialed providers. The wrapper forwards them only as `X-Provider`, `X-Provider-Model`, and `X-Provider-Key` headers on `POST /v1/runs`.

The key is omitted from tool arguments, request bodies, non-run requests, repr output, and errors. A partial configuration fails before the server starts, and an installed engine without provider-credential support fails closed rather than silently sending an unauthenticated run.

## Tenant usage awareness

Usage is scoped by the `ADAPTORCH_CONTROL_PLANE_TOKEN` you configure. The control plane
resolves the tenant from that key, so `adaptorch_usage` takes **no arguments** and a
client cannot ask for another tenant's numbers — an extra argument is rejected with
JSON-RPC `-32602`.

| Field | Meaning |
| --- | --- |
| `tenant_id` | Your own tenant, as resolved from the key |
| `plan_level` | Plan the limit came from (`starter`, `pro`, `team`) |
| `period` | UTC billing period the counter belongs to |
| `used` / `limit` / `remaining` | Run counter for the period (`limit` may be unlimited) |
| `usage_percentage` | `used / limit` as a percentage |

The wrapper projects only those fields; counter sources, database rows, and any other
control-plane internals are dropped.

When a run is rejected because the period counter is exhausted, the tool result is an
error payload rather than a masked internal failure:

```json
{
  "error": "QUOTA_EXCEEDED",
  "message": "tenant quota exhausted for the current period (used=1000, limit=1000); upgrade at /pricing",
  "usage": { "limit": 1000, "used": 1000, "remaining": 0, "upgrade_url": "/pricing" }
}
```

The engine does not retry that response: a monthly counter only resets at the period
boundary. A `429 RATE_LIMITED` (burst limiting) is still retried as before.

## Structured run output

In the remote profile, `adaptorch_get_run` advertises a closed MCP `outputSchema` and returns both the legacy JSON text block and an equivalent safe `structuredContent` mapping. When the installed AdaptOrch control plane provides `correctness_wall`, the wrapper projects only bounded verdict, blocker, advisory, evidence-note, recommendation, and claim-boundary fields. A `PASS` verdict is evidence-gate observability only—not a correctness proof, active-selector decision, Full50 GO result, or authorization to apply a candidate.

## Resources and templates

The installed engine exposes four static resources and two run resource templates.

| URI | Type | Purpose |
| --- | --- | --- |
| `adaptorch://tools` | resource | Tool registry summary. |
| `adaptorch://connectors` | resource | Available connector names. |
| `adaptorch://server-info` | resource | Protocol and server metadata. |
| `adaptorch://plans/cloud` | resource | Hosted cloud plan catalog. |
| `adaptorch://runs/{run_id}/summary` | template | Run summary resource template. |
| `adaptorch://runs/{run_id}/artifacts` | template | Run artifacts resource template. |

## Prompts

| Prompt | Purpose |
| --- | --- |
| `adaptorch_run_prompt` | Template for calling `adaptorch_run` with a task prompt, optional context, and synthesis mode. |
| `adaptorch_get_run_prompt` | Template for calling `adaptorch_get_run` by `run_id`. |

## Public Verification

Use the smoke command after installation:

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.com
```

The smoke command checks `initialize`, `tools/list`, and the expected core tool subset without printing token values. It is a subset smoke, not a full surface conformance test. Add repeatable `--expected-tool <name>` flags when validating a specific hosted/core release.

## Auto-approve guidance

For trusted local clients, auto-approve only tools whose outputs are safe for that client. Keep `adaptorch_run` and `adaptorch_cancel_run` manually approved. For shared or production clients, avoid auto-approving run, artifact, and trace readers unless those payloads are already sanitized.
