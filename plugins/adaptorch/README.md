# AdaptOrch plugin for Claude Code

Run multi-step coding tasks on the hosted AdaptOrch service from Claude Code and get run
receipts, artifacts and evidence back in the conversation.

## Install

Requires [`uv`](https://docs.astral.sh/uv/) on your `PATH`.

```bash
claude plugin marketplace add dmae97/Adaptorch-MCP
claude plugin install adaptorch@adaptorch
```

Or inside a session: `/plugin install adaptorch --marketplace dmae97/Adaptorch-MCP`.

## API key

Create a free account at https://adaptorch.com/app/signup and a key at
https://adaptorch.com/app/api-keys (it starts with `ado_`). Claude Code asks for the key
when you enable the plugin and keeps it in its secure credential store. To set or change
it later, run `/plugin configure adaptorch@adaptorch`, then `/reload-plugins`.

Without a key the tools still appear, and each call returns
`ADAPTORCH_CONTROL_PLANE_TOKEN is not configured`.

## What it adds

- **MCP server `adaptorch`**: `uvx --python 3.12 --from "adaptorch-mcp>=0.6,<0.7"
  adaptorch-mcp-client --transport stdio`, in the `remote` exposure profile. It forwards
  calls to adaptorch.com and runs no orchestration locally.
- **Skill `adaptorch`**: when to submit a run, how to poll and cancel it, how to read the
  plan and usage, and how to report results without overstating them.

Tools: `adaptorch_run`, `adaptorch_get_run`, `adaptorch_list_runs`,
`adaptorch_get_artifacts`, `adaptorch_cancel_run`, `adaptorch_capabilities`,
`adaptorch_usage`, `adaptorch_plan_catalog`, `adaptorch_server_metrics`.

Each submitted run counts against your plan. Plans: https://adaptorch.com/pricing.
