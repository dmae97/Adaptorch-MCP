# Glama listing build spec

Glama does not build the repository `Dockerfile`. It generates its own image
(Debian, Node, `mcp-proxy`, uv-managed Python), clones this repository, checks out
the pinned commit (default: latest synced `main`), runs the **Build steps**, then
starts `mcp-proxy -- <CMD arguments>` and sends `initialize` and `tools/list`.

## Why the first build failed

On `main` the workspace still resolves the private `adaptorch` engine from
`github.com/dmae97/adaptorch`, so `uv` stops with
`fatal: could not read Username for 'https://github.com'`. Two smaller traps:
console scripts land outside `PATH` in Glama's uv Python, and that Python is
marked externally managed.

## Admin → Dockerfile values

| Field | Value |
| --- | --- |
| Python version | `3.12` (the package requires `<3.13`) |
| Build steps | see below |
| CMD arguments | `["python", "-u", "-m", "adaptorch_mcp", "--transport", "stdio"]` |
| Environment variables JSON schema | see below |
| Placeholder parameters | `{}` |
| Pinned commit SHA | empty |

Build steps (one JSON array, one string):

```json
["uv pip install --system --break-system-packages --python python 'adaptorch-client @ git+https://github.com/dmae97/Adaptorch-MCP@864a4ef3b21ab21d050fe5aa9c2846f93668828a#subdirectory=packages/adaptorch-client' 'adaptorch-mcp @ git+https://github.com/dmae97/Adaptorch-MCP@864a4ef3b21ab21d050fe5aa9c2846f93668828a#subdirectory=packages/adaptorch-mcp'"]
```

The step installs from one pinned public commit, so it works whichever commit
Glama checks out. Do not put `mcp-proxy` in CMD; Glama adds it.

Environment variables JSON schema:

```json
{"type":"object","properties":{"ADAPTORCH_CONTROL_PLANE_TOKEN":{"type":"string","description":"AdaptOrch API key (ado_...). Optional for introspection; required for tool calls."}},"required":[]}
```

Never put a real token in placeholder parameters. Without a token the server
answers `initialize`, `ping` and `tools/list` from the pinned catalog and refuses
every tool call with `-32001`.

## After a green build

1. Click **Make Release** on the successful test and publish a version.
2. Check that the Schema tab lists 9 tools and the listing no longer says
   "This server cannot be deployed".
3. Only then add the score badge to the awesome-mcp-servers entry.

The license grade stays F while the repository is proprietary.

## Local reproduction

The same steps were checked in a `debian:trixie-slim` image with `mcp-proxy@6.4.3`
and uv Python 3.12 against a clean `main` clone: install succeeded, `initialize`
and `ping` answered through `mcp-proxy`, and `tools/list` returned 9 tools. That
image approximates Glama's builder; it is not Glama's own image.
