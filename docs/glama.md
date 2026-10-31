# Glama listing build spec

Glama does not build the repository `Dockerfile`. It generates its own image
(Debian, Node, `mcp-proxy`, uv-managed Python), clones this repository, checks out
the pinned commit (default: latest synced `main`), runs the **Build steps**, then
starts the **CMD arguments** and sends `initialize` and `tools/list`.

## Admin → Dockerfile values

These values passed the Glama build test on `main` at `cc1fa8a` and the listing
now shows 9 tools.

| Field | Value |
| --- | --- |
| Python version | `3.12` (the package requires `<3.13`) |
| Build steps | `["uv pip install --system --break-system-packages --python python ./packages/adaptorch-client ./packages/adaptorch-mcp"]` |
| CMD arguments | `["mcp-proxy", "--", "python", "-u", "-m", "adaptorch_mcp", "--transport", "stdio"]` |
| Environment variables JSON schema | see below |
| Placeholder parameters | `{}` |
| Pinned commit SHA | empty (builds the latest synced `main`) |

Environment variables JSON schema:

```json
{"type":"object","properties":{"ADAPTORCH_CONTROL_PLANE_TOKEN":{"type":"string","description":"AdaptOrch API key (ado_...). Optional for introspection; required for tool calls."}},"required":[]}
```

Never put a real token in placeholder parameters. Without a token the server
answers `initialize`, `ping` and `tools/list` from the packaged catalog and
refuses every tool call with `-32001`.

### Default values Glama may restore

The form has come back with values that were not entered: Build steps
`["uv sync"]` and a CMD ending in `--base-url https://adaptorch.com` (the same
command as the `docs/configuration.md` example). Both are handled:

- The root `pyproject.toml` depends on the `adaptorch-client` and `adaptorch-mcp`
  workspace members, so a bare `uv sync` installs the server into `.venv`. With
  that build step use CMD
  `["mcp-proxy", "--", "uv", "run", "adaptorch-mcp", "--transport", "stdio"]`.
  The system `python` does not see `.venv`, so `python -m adaptorch_mcp` only
  works with the `uv pip install --system` build step above.
- Drop `--base-url https://adaptorch.com` from any CMD. Glama rejects URLs in
  the spec ("CMD cannot contain URLs"), and the hosted URL is already the default.

## Form pitfalls

- **Pinned commit:** Glama only accepts commits it knows from syncing `main`. A
  commit that exists only on a branch fails with "Must be a valid Git SHA", and
  an invalid field blocks saving the whole form. Reload the page after **Save**
  and confirm the build log's `[4/5]` line checks out the expected commit.
- **Spaces in build steps:** `--python python./packages/...` (missing space)
  makes uv look for a Python at that path and fail with
  "No system Python installation found".
- **No URLs anywhere in the spec,** including `git+https://` installs in build
  steps.

## Earlier failures

- Before the thin runtime was merged, the workspace resolved the private
  `adaptorch` engine from `github.com/dmae97/adaptorch`, so `uv` stopped with
  `fatal: could not read Username for 'https://github.com'`. The public install
  now needs only `adaptorch-client`; the engine is behind the `engine-dev` extra.
- With Build steps `["uv sync"]` and no root dependencies, `uv sync` installed
  nothing and the server exited with `No module named adaptorch_mcp`.

## After a green build

1. Click **Make Release** on the successful test and publish a version.
2. Check that the Schema tab lists 9 tools and the listing no longer says
   "This server cannot be deployed".
3. Only then add the score badge to the awesome-mcp-servers entry.

The license grade stays F while the repository is proprietary.
