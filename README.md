# AdaptOrch public clients

AdaptOrch clients submit work to the hosted service and read available run status,
bounded observations and artifact references. Routing and execution stay server-side;
private engine algorithms are not included in these public distributions.

## Packages

- [Python SDK](packages/adaptorch-client/README.md): `pip install adaptorch-client`
- [Terminal CLI](packages/adaptorch-cli/README.md): `pip install adaptorch-cli`
- [Convenience package](packages/adaptorch/README.md): SDK/CLI meta-package
- [MCP0.6 candidate](packages/adaptorch-mcp/README.md): remote-only stdio bridge

SDK/CLI/meta package source and release metadata are unchanged by the MCP migration.
The MCP0.6 candidate is unreleased until separately approved and published.

## MCP0.6 connection

Install the approved MCP wheel in a fresh Python 3.11/3.12 virtual environment,
following the [candidate install instructions](packages/adaptorch-mcp/README.md#install-and-launch).
Then use that environment's explicit launcher:

```sh
export ADAPTORCH_CONTROL_PLANE_TOKEN='<tenant-api-key>'
export ADAPTORCH_MCP_PROVIDER='<provider>'
export ADAPTORCH_MCP_PROVIDER_MODEL='<model>'
export ADAPTORCH_MCP_PROVIDER_API_KEY='<provider-key>'
.venv-mcp/bin/adaptorch-mcp-client --base-url https://adaptorch.com
```

Explicit `--base-url` takes precedence over `ADAPTORCH_CONTROL_PLANE_BASE_URL`,
then the hosted default. Only HTTPS origins are permitted by default. Tenant and
provider credentials are process-local; provider headers are sent only on submission.
No provider keys are searched from ambient environment variables.

See the [complete MCP guide](packages/adaptorch-mcp/README.md) for supported input
fields, two stdio framings, OAuth, safe artifacts, timing and compatibility limits.
The [Claude Desktop](examples/claude_desktop_config.json) and
[OMK](examples/omk.mcp.json) examples contain placeholders and no automatic approvals.

## Nine tools, bounded exposure

The public bridge exposes run, get_run, get_artifacts, list_runs, cancel_run,
server_metrics, capabilities, usage and plan_catalog. It validates the hosted
inventory and projects each result locally. Traces/topology, arbitrary resources,
completions and commands are unavailable. Metrics/lifecycle are client-process local.

Known limitations are explicit: idempotency/resume are rejected; completed artifacts
represented as filesystem paths or opaque storage keys are unavailable; query/signed
URLs are blocked. Safe structural URI validation is not proof about unknown tokens in
URL paths. No artifact is fetched automatically, no link invented, and an observer
timeout never triggers retry or cancellation. Read the package guide before first use.

## Breaking migration from0.5

Use a fresh environment for 0.6 rather than upgrading an existing 0.5/private-engine
installation in place. Point the MCP host at the new environment's absolute
`adaptorch-mcp-client` path; an older `adaptorch-mcp` script elsewhere on PATH may
still belong to the old wrapper or engine. The public0.6 package does not support
full/local-engine/local-HTTP mode, provider auto/keyless/
key-command/fallback, or non-loopback plaintext escapes. Private engine usage belongs
in a separate private distribution. Historical0.5 instructions are available in Git;
they must not be used to install this client.

## Development and verification

```sh
uv sync --locked --all-packages --extra dev
uv run ruff check packages/adaptorch-mcp packages/adaptorch-client packages/adaptorch-cli
uv run mypy
uv run pytest
uv run adaptorch-mcp-doctor --json
uv run python scripts/check_public_wheels.py --package adaptorch adaptorch-client adaptorch-cli adaptorch-mcp
```

CI covers Python3.11/3.12 and installs built MCP wheels in a clean public-only runtime.
Offline fixtures prove client contracts, not live service/provider execution. Production
first-use, publication and deployment require their own authorization and verification.

## Security and ownership

See [SECURITY.md](SECURITY.md), [PUBLICATION.md](PUBLICATION.md) and the canonical
[LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
