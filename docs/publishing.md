# Publishing to pip / uv

`uv` installs from Python package indexes such as PyPI; there is no separate uv registry. Publishing to PyPI makes the package available to both:

```bash
pip install adaptorch-mcp
uvx --from "adaptorch-mcp==0.5.1" adaptorch-mcp-client --help
```

## Package dependency order

`adaptorch-mcp` delegates runtime behavior to `adaptorch.mcp_server`. The 0.5.x
wrapper supports the existing `adaptorch` 0.1.x engine and excludes the planned
code-free 0.2.x meta-package. This wrapper release does not republish private
engine code, the API client, the CLI, or the meta-package.

1. Verify against the already published compatible engine and the CI-pinned source.
2. Publish only the wrapper after test, package, and install checks pass.
3. Smoke-test the unambiguous `adaptorch-mcp-client` launcher in a clean environment.

If `adaptorch` is not on PyPI yet, users can still install from GitHub:

```bash
pip install "adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git"
pip install adaptorch-mcp
```

## Local build and checks

From this monorepo root:

```bash
uv sync --all-packages --extra dev
uv run ruff check packages/adaptorch-mcp
uv run mypy packages/adaptorch-mcp/src
uv run pytest packages/adaptorch-mcp/tests -q
uv run python -m build packages/adaptorch-mcp --outdir dist
uv publish --dry-run dist/*
```

Before publishing, verify documentation and examples cover install, stdio, HTTP,
doctor, smoke, tool lists, prompts, engine-delegated optional controls, HTTP
auth, max payload, request timeout, and placeholder-only example values.

Run a redacted secret scan and store the evidence:

```bash
gitleaks detect --source . --redact
```

## Local global refresh from current AdaptOrch source

Build immutable wheel snapshots for both the wrapper and the current local AdaptOrch tree, record their SHA-256 hashes, then install only those artifacts:

```bash
uv run --no-sync python -m build packages/adaptorch-mcp --outdir dist
uv run --no-sync python -m build --wheel \
  --outdir /absolute/path/to/core-dist /absolute/path/to/adaptorch
sha256sum \
  dist/adaptorch_mcp-0.5.1-py3-none-any.whl \
  /absolute/path/to/core-dist/adaptorch-0.1.2-py3-none-any.whl
uv tool install --offline --force \
  --with "adaptorch[api] @ file:///absolute/path/to/core-dist/adaptorch-0.1.2-py3-none-any.whl" \
  dist/adaptorch_mcp-0.5.1-py3-none-any.whl
```

Both distributions publish an `adaptorch-mcp` console script. Prefer the wrapper-only
`adaptorch-mcp-client` command. If an existing client requires the legacy name,
restore that entry point after installing the core and verify its import target:

```bash
uv pip install --offline \
  --python "$HOME/.local/share/uv/tools/adaptorch-mcp/bin/python" \
  --force-reinstall --no-deps \
  dist/adaptorch_mcp-0.5.1-py3-none-any.whl
grep -q "from adaptorch_mcp.cli import main" \
  "$HOME/.local/share/uv/tools/adaptorch-mcp/bin/adaptorch-mcp"
```

Run `adaptorch-mcp-smoke` afterward and require the default remote surface to contain exactly nine tools. Do not use a deleted temporary source directory as the uv receipt origin.

## Real PyPI publish with uv

Use a PyPI token only in your shell/session or CI secret store. Do not commit it.

```bash
export UV_PUBLISH_TOKEN="<pypi-token>"
uv publish dist/*
```

For TestPyPI:

```bash
export UV_PUBLISH_TOKEN="<testpypi-token>"
uv publish \
  --publish-url https://test.pypi.org/legacy/ \
  --check-url https://test.pypi.org/simple/adaptorch-mcp/ \
  dist/*
```

## Trusted Publishing

The preferred public release path is GitHub Actions Trusted Publishing:

1. Create the PyPI project `adaptorch-mcp`.
2. In PyPI, add a trusted publisher for this repository.
3. Require the GitHub `pypi` environment.
4. Tag a release like `adaptorch-mcp-v0.5.1`.
5. Let `.github/workflows/publish.yml` build and publish without storing a PyPI API token.

## One workflow, four packages

`publish.yml` reads the package and the version from the tag name:

| Tag | Publishes | Notes |
| --- | --- | --- |
| `adaptorch-client-v<version>` | `packages/adaptorch-client` | stdlib-only hosted API client |
| `adaptorch-cli-v<version>` | `packages/adaptorch-cli` | `adaptorchctl`; depends on `adaptorch-client` |
| `adaptorch-v<version>` | `packages/adaptorch` | meta-package: installs client + cli, no code |
| `adaptorch-mcp-v<version>` | `packages/adaptorch-mcp` | local-engine wrapper |

The tag version must equal the package's `pyproject.toml` version, and every
wheel passes `scripts/check_public_wheels.py` (no engine code, no dependency on
the `adaptorch` core distribution) before upload. Order for a first release of
the meta-package: `adaptorch-client` → `adaptorch-cli` → `adaptorch`, because
the meta-package pins both. Run the gate locally first:

```bash
uv run python scripts/check_public_wheels.py --package adaptorch adaptorch-client adaptorch-cli
```

## Post-publish smoke

```bash
uvx --from "adaptorch-mcp==0.5.1" adaptorch-mcp-client --help
uvx --with "adaptorch[api]" adaptorch-mcp-doctor --json
ADAPTORCH_CONTROL_PLANE_TOKEN="<token>" \
  uvx --with "adaptorch[api]" adaptorch-mcp-smoke --base-url https://adaptorch.com
```

Expected MCP tools include `adaptorch_plan_catalog`. For HTTP, also verify `/mcp/health`, `initialize`, and `tools/list` with a client-facing `ADAPTORCH_MCP_HTTP_AUTH_TOKEN`.
