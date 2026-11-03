# AdaptOrch for Claude Code

The Claude Code plugin connects to the hosted AdaptOrch service with the public MCP
client. It includes a skill for submitting requested tasks and inspecting run status,
available artifacts and usage. The private engine stays on the hosted service.

## Install and configure

Install [uv](https://docs.astral.sh/uv/), then add this repository's marketplace:

```bash
claude plugin marketplace add dmae97/Adaptorch-MCP
claude plugin install adaptorch@adaptorch
```

Create an account and service API key at <https://adaptorch.com/app/api-keys>. In Claude
Code, run `/plugin configure adaptorch@adaptorch` and enter the key in the configuration
dialog. To submit a model-backed run, also configure the provider, exact model ID and
provider API key. Run `/reload-plugins` after changing settings. The current Claude model
is not automatically supplied to the remote service. See the
[plugin README](../plugins/adaptorch/README.md) for details.

Never paste a service key or provider key into chat, prompts or tool arguments. Do not
submit private code or context unless the user has authorized sending it to AdaptOrch.
Submissions can consume plan quota and provider tokens can have separate charges; see
<https://adaptorch.com/pricing>.

## First use

1. Check the plugin and MCP connection with `/plugin` and `/mcp`.
2. Ask to see AdaptOrch plan usage or recent runs. These do not submit a new run.
3. When the user requests a task, submit it with `adaptorch_run` and check its status with
   `adaptorch_get_run`. Retrieve available artifacts with `adaptorch_get_artifacts`.

The actual advertised tool list and schemas are authoritative. Discovery without a
service key confirms that the local client started; it does not prove hosted
authentication, model execution or end-to-end correctness. Do not automatically retry a
submission after a timeout: it may already have succeeded.

The plugin is independently distributed through this repository. Listing in Anthropic's
directory requires a separate submission and review. See
[agent platform integrations](agent-platform-integrations.md) for other hosts and
distribution status.
