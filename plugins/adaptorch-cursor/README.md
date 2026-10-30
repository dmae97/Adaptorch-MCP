# AdaptOrch plugin for Cursor

Run multi-step coding tasks on the hosted [AdaptOrch](https://adaptorch.com) service and get run status, artifacts, usage and replayable evidence receipts back in chat.

## Components
- `mcp.json` — `adaptorch` MCP server: `uvx --from adaptorch-mcp==0.6.0 adaptorch-mcp-client --transport stdio` (thin client to the hosted control plane; Python 3.12 via uv).
- `skills/adaptorch` — when and how to use the AdaptOrch tools.

## Requirements
- [uv](https://docs.astral.sh/uv/) installed (`uvx` on PATH).
- AdaptOrch API key from https://adaptorch.com/app/api-keys (starts with `ado_`).

## Setup
Set these as plugin variables (team admins: dashboard → Plugins → Configure), then reload MCP servers:

| Variable | Needed for |
|---|---|
| `ADAPTORCH_CONTROL_PLANE_TOKEN` | all tool calls |
| `ADAPTORCH_MCP_PROVIDER`, `ADAPTORCH_MCP_PROVIDER_MODEL`, `ADAPTORCH_MCP_PROVIDER_API_KEY` | model runs (BYOK; leave empty for read-only queries) |

Never paste keys into chat or commit them.

## Links
Docs https://adaptorch.com/mcp-docs · Privacy https://adaptorch.com/privacy · Terms https://adaptorch.com/terms · Source https://github.com/dmae97/Adaptorch-MCP

## License
Proprietary — see `LICENSE`.
