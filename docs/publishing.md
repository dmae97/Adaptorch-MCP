# Publishing to pip / uv

`uv` installs from Python package indexes such as PyPI; there is no separate uv registry. Publishing to PyPI makes the package available to both:

```bash
pip install adaptorch-mcp
uvx adaptorch-mcp --help
```

## Package dependency order

`adaptorch-mcp` delegates runtime behavior to `adaptorch.mcp_server`, so publish order matters:

1. Publish `adaptorch` core with the latest MCP server/tool surface.
2. Publish `adaptorch-mcp` wrapper.
3. Smoke-test `pipx`, `uvx`, and MCP client configs.

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
4. Tag a release like `adaptorch-mcp-v0.3.0`.
5. Let `.github/workflows/publish.yml` build and publish without storing a PyPI API token.

## Post-publish smoke

```bash
uvx adaptorch-mcp --help
uvx --with "adaptorch[api]" adaptorch-mcp-doctor --json
ADAPTORCH_CONTROL_PLANE_TOKEN="<token>" \
  uvx --with "adaptorch[api]" adaptorch-mcp-smoke --base-url https://adaptorch.com
```

Expected MCP tools include `adaptorch_plan_catalog`. For HTTP, also verify `/mcp/health`, `initialize`, and `tools/list` with a client-facing `ADAPTORCH_MCP_HTTP_AUTH_TOKEN`.
