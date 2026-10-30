# Publishing to pip / uv

`uv` installs from Python package indexes such as PyPI; there is no separate uv registry. Publishing to PyPI makes the package available to both:

```bash
pip install adaptorch-mcp
uvx --from "adaptorch-mcp==0.6.0" adaptorch-mcp-client --help
```

## Package dependency order

Since 0.6.0 `adaptorch-mcp` is a remote client: its only runtime dependency is
`adaptorch-client`, and it never installs or imports the private engine. The
in-process engine bridge (`hardening`, `runtime`, `control_plane_backend`,
`backend_config`) lives in `packages/adaptorch-mcp/legacy/adaptorch_mcp_legacy`,
outside `src/`, and is not part of any distribution. Maintainers install the engine
for parity tests with `uv sync --all-packages --extra dev --group engine` or
`make engine-check`.

1. Publish `adaptorch-client` first if the wrapper needs a newer client.
2. Publish the wrapper after test, package, public wheel gate and install checks pass.
3. Smoke-test the `adaptorch-mcp-client` launcher in a clean environment.

`adaptorch-mcp` 0.3.0–0.5.2 on PyPI depend on the engine distribution and do not
work against the code-free `adaptorch` 0.2.0 meta-package; 0.6.0 replaces them.

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

## Local global refresh

Build an immutable wheel snapshot, record its SHA-256 hash, then install only that
artifact:

```bash
uv run --no-sync python -m build packages/adaptorch-mcp --outdir dist
sha256sum dist/adaptorch_mcp-0.6.0-py3-none-any.whl
uv tool install --force dist/adaptorch_mcp-0.6.0-py3-none-any.whl
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
4. Tag a release like `adaptorch-mcp-v0.6.0`.
5. Let `.github/workflows/publish.yml` build and publish without storing a PyPI API token.

## One workflow, four packages

`publish.yml` reads the package and the version from the tag name:

| Tag | Publishes | Notes |
| --- | --- | --- |
| `adaptorch-client-v<version>` | `packages/adaptorch-client` | stdlib-only hosted API client |
| `adaptorch-cli-v<version>` | `packages/adaptorch-cli` | `adaptorchctl`; depends on `adaptorch-client` |
| `adaptorch-v<version>` | `packages/adaptorch` | meta-package: installs client + cli, no code |
| `adaptorch-mcp-v<version>` | `packages/adaptorch-mcp` | remote MCP client; depends on `adaptorch-client` |

The tag version must equal the package's `pyproject.toml` version, and every
wheel passes `scripts/check_public_wheels.py` (no engine code, no dependency on
the `adaptorch` core distribution, no module-level engine import) before upload. Order for a first release of
the meta-package: `adaptorch-client` → `adaptorch-cli` → `adaptorch`, because
the meta-package pins both. Run the gate locally first:

```bash
uv run python scripts/check_public_wheels.py --package adaptorch adaptorch-client adaptorch-cli adaptorch-mcp
```

## Post-publish smoke

```bash
uvx --from "adaptorch-mcp==0.6.0" adaptorch-mcp-client --help
uvx --from "adaptorch-mcp==0.6.0" adaptorch-mcp-doctor --json
ADAPTORCH_CONTROL_PLANE_TOKEN="<token>" \
  uvx --from "adaptorch-mcp==0.6.0" adaptorch-mcp-smoke --base-url https://adaptorch.com
```

Expected MCP tools include `adaptorch_plan_catalog`. For HTTP, also verify `/mcp/health`, `initialize`, and `tools/list` with a client-facing `ADAPTORCH_MCP_HTTP_AUTH_TOKEN`.
