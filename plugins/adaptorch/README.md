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

Create an account at https://adaptorch.com/app/signup and a service key at
https://adaptorch.com/app/api-keys. In Claude Code run
`/plugin configure adaptorch@adaptorch`, then `/reload-plugins`.

Enter the service key in the configuration dialog. For model-backed runs, also enter the
provider, its exact model ID, and its API key. Leave all three provider fields empty for
read-only account and existing-run queries. Claude Code treats the two keys as sensitive
configuration; do not paste them into chat or tool arguments. If a graphical surface does
not offer configuration, use Claude Code's terminal interface.

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

Submissions can consume plan quota; model tokens can be billed separately by the provider.
The current chat model is not automatically available to the hosted service. Plans:
https://adaptorch.com/pricing. The plugin sends approved prompts and context to AdaptOrch.
