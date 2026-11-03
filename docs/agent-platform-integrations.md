# AdaptOrch agent integrations

These AdaptOrch-maintained packages connect an agent to the hosted service. They do not
ship the private orchestration engine. A self-hosted marketplace and a reviewed listing
in a platform's official directory are different things; the packages here do not imply
an upstream listing or endorsement.

| Host | Package in this repository | Distribution |
| --- | --- | --- |
| Claude Code | `plugins/adaptorch` | AdaptOrch marketplace; separate directory review required |
| Kimi Code CLI | root `kimi.plugin.json` | Install from this repository; not a Kimi-maintained plugin |
| Grok Build | `plugins/adaptorch-grok` | AdaptOrch marketplace; separate xAI catalog PR required |
| Cursor / Grok Bot | `plugins/adaptorch-cursor` | Cursor-format package; Grok Bot listing requires review and in-app testing |

All three stdio integrations need `uvx` on PATH and run the published remote client.
Its first launch can download Python 3.12 and the package from PyPI. The client sends
approved tool inputs to AdaptOrch over HTTPS. A requested model run may consume plan
quota and incur provider charges; account and existing-run queries do not submit a run.
See [privacy](https://adaptorch.com/privacy), [terms](https://adaptorch.com/terms), and
[connection docs](https://adaptorch.com/mcp-docs).

## Authentication

The AdaptOrch service key and model provider key are distinct. Create the service key at
<https://adaptorch.com/app/api-keys>. For a model-backed run, configure a supported
provider, its exact model ID and provider key as well. A host's logged-in model is not
automatically available for a remote run.

Claude Code prompts for these fields in its plugin configuration dialog. For Kimi Code
CLI and Grok Build, configure the following in the environment of the process that starts
the host; restart the host after changes:

| Variable | Purpose |
| --- | --- |
| `ADAPTORCH_CONTROL_PLANE_TOKEN` | AdaptOrch service key |
| `ADAPTORCH_MCP_PROVIDER` | Model provider for requested model runs |
| `ADAPTORCH_MCP_PROVIDER_MODEL` | Exact model ID |
| `ADAPTORCH_MCP_PROVIDER_API_KEY` | Provider key for requested model runs |

Keep all provider variables unset for read-only operations. In a Bash terminal, enter
secrets without placing them in shell history:

```bash
read -r -s -p 'AdaptOrch service key: ' ADAPTORCH_CONTROL_PLANE_TOKEN; printf '\n'
export ADAPTORCH_CONTROL_PLANE_TOKEN

# Only for model-backed runs:
read -r -p 'Provider: ' ADAPTORCH_MCP_PROVIDER
read -r -p 'Model ID: ' ADAPTORCH_MCP_PROVIDER_MODEL
read -r -s -p 'Provider key: ' ADAPTORCH_MCP_PROVIDER_API_KEY; printf '\n'
export ADAPTORCH_MCP_PROVIDER ADAPTORCH_MCP_PROVIDER_MODEL ADAPTORCH_MCP_PROVIDER_API_KEY
```

These values remain in the process environment for that session. Use the host's secure
configuration where available. Never put keys in chat, prompts, tool arguments, a
committed config or screenshots. Do not start a paid run merely to check installation.

## Claude Code

```bash
claude plugin marketplace add dmae97/Adaptorch-MCP
claude plugin install adaptorch@adaptorch
```

In a Claude Code session, run `/plugin configure adaptorch@adaptorch`, enter the service
key and optionally the provider fields, and run `/reload-plugins`. The plugin adds a
skill and an MCP server; use `/mcp` to check connection. Graphical hosts may have
different configuration support: use the terminal interface if no configuration dialog
is offered. See [plugin details](../plugins/adaptorch/README.md). A Claude directory
listing is submitted through the [developer portal](https://platform.claude.com/plugins/submit)
and is subject to separate review.

## Kimi Code CLI

Use the current Node.js-based Kimi Code CLI with plugin support, not the older Python
`kimi-cli`. Set the environment variables above in the terminal, then start `kimi`. In a
session install the explicit main-branch source:

```text
/plugins install https://github.com/dmae97/Adaptorch-MCP/tree/main
/reload
```

Pin a reviewed commit with the documented GitHub commit URL form for reproducible
installs. An explicit ref matters because an unqualified GitHub URL can resolve to an
older release. Check `/plugins info adaptorch` for diagnostics and `/mcp` for the
server. Invoke `/skill:adaptorch:adaptorch` or ask for an AdaptOrch operation. Plugin
changes apply in a new or reloaded session. Kimi Work's plugin import is a separate
product path and has not been validated by these CLI instructions.

## Grok Build

Set the environment above before starting Grok Build. Add this repository as a marketplace
and install the plugin:

```bash
grok plugin marketplace add dmae97/Adaptorch-MCP
grok plugin install adaptorch --trust
grok inspect
```

Review the package before granting trust. `grok inspect`, `/plugins` and `/mcps` can
show the plugin, skill and MCP server. Restart Grok after changing environment variables.
The published package is pinned to `adaptorch-mcp==0.6.1`; its `uvx` process is local,
while task execution is hosted. See [plugin details](../plugins/adaptorch-grok/README.md).

## Grok Bot / Cursor

The existing [Cursor-format plugin](../plugins/adaptorch-cursor/README.md) contains a
skill, MCP config and user variables. Grok Bot can also connect custom MCP servers; for
remote HTTPS clients, <https://adaptorch.com/mcp> is the documented endpoint. Confirm
the host's supported authentication and provider-header configuration before relying on
model-backed runs. Static HTTP headers may be sent with every request and may be stored by
the host: do not treat this as equivalent to the stdio client's submission-only BYOK.

Grok Bot's [submission form](https://x.ai/bot/marketplace/submit-a-plugin) requires
local **and in-app** testing, publisher details, and acceptance of publisher terms.
Do not claim the package is listed or that it has passed those tests until the platform
has actually accepted it. A Grok Build catalog listing has a separate
[contribution process](https://github.com/xai-org/plugin-marketplace).

## Troubleshooting

- If tools do not appear, check that `uvx` is on the host's PATH, the plugin is enabled
  and trusted, and the session has been reloaded. Inspect the host's diagnostics.
- A missing or rejected service key prevents authenticated calls. Configure it outside
  chat and restart the host. In the wrapper's discovery-only mode `tools/list` can still
  work without a key; this does not verify hosted connectivity.
- A model run requires valid provider settings. A timeout after submission is ambiguous;
  look at existing runs before retrying to avoid an accidental duplicate.
- A successful receipt or passing check does not prove correctness or authorize release.
