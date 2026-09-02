# adaptorch

**Your AI says it works. AdaptOrch checks.**

AdaptOrch runs AI-written patches in a clean project copy, separates code
failures from runner failures, and returns one replayable receipt. Multi-model
runs get the same receipt: which model answered, where they disagreed, and what
it cost.

This distribution is a meta-package. It contains no code of its own; it installs
the two thin clients for the hosted service at <https://adaptorch.com>:

| Installs | What it is |
| --- | --- |
| [`adaptorch-client`](https://pypi.org/project/adaptorch-client/) | Standard-library Python client for User API v1 (`https://adaptorch.com/v1`) |
| [`adaptorch-cli`](https://pypi.org/project/adaptorch-cli/) | The `adaptorchctl` command |

```bash
pip install adaptorch          # or: uv tool install adaptorch
export ADAPTORCH_API_KEY="ado_..."   # create one at https://adaptorch.com/app/api-keys
adaptorchctl whoami
```

```python
import os

from adaptorch_client import AdaptOrchClient, ClientConfig

client = AdaptOrchClient(
    ClientConfig(api_url="https://adaptorch.com", api_key=os.environ["ADAPTORCH_API_KEY"])
)
print(client.capabilities())
```

Using a coding agent instead of Python? Nothing to install:

```bash
claude mcp add --transport http adaptorch https://adaptorch.com/mcp \
  --header "Authorization: Bearer ${ADAPTORCH_API_KEY}"
```

Cursor, Codex, Gemini CLI, VS Code and Windsurf snippets: <https://adaptorch.com/mcp-docs>.

## What is not in here

The verification engine and the control plane are not distributed as a package;
they run in the hosted service. Releases 0.1.1 and 0.1.2 of this name were
earlier reference implementations and are withdrawn.

## License

Proprietary — Copyright (c) 2026 ClassicMate. All rights reserved. See
[LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/packages/adaptorch/LICENSE).
