# Authenticated PESCO routing advice

This document records the routing contract and local evidence, not a production
deployment or package-publication claim. Routing release versions:
`adaptorch-client 0.1.7`, `adaptorch-cli 0.1.7`, `adaptorch-mcp 0.6.2`.
Install the matching client and wrapper wheels together when testing locally.

## One engine, three entry points

The public packages do not contain the private routing engine. They use the existing
key-authenticated `POST /v1/mcp` endpoint and its `adaptorch_route_topology` tool.
The hosted engine owns DAG validation, topology selection, stages, PESCO policy and
cost advice. No run, provider request, BYOK header or monthly quota debit is created.
A missing, invalid or revoked tenant key is refused even for routing advice.

CLI:

```sh
adaptorchctl route --file dag.json
# Or: adaptorchctl route --file - < dag.json
```

`dag.json` is a routing argument object, not a run submission:

```json
{
  "subtasks": [
    {"id": "inspect", "description": "Inspect the input"},
    {"id": "verify", "description": "Verify the result"}
  ],
  "dependencies": [{"from": "inspect", "to": "verify"}],
  "prefer_ensemble_singleton": false
}
```

SDK (credentials are resolved by the caller, not included in the DAG):

```python
import os
from adaptorch_client import AdaptOrchClient, ClientConfig

with AdaptOrchClient(ClientConfig(
    api_url="https://adaptorch.com",
    api_key=os.environ["ADAPTORCH_API_KEY"],
)) as client:
    advice = client.route_topology({
        "subtasks": [{"id": "inspect", "description": "Inspect the input"}],
        "prefer_ensemble_singleton": False,
    })
    print(advice.topology)
    print(advice.to_payload())
```

Thin MCP advertises the optional route tool in offline discovery and forwards calls
only with configured credentials. Discovery without credentials never executes the
router. Live `tools/list` still reflects the service, so an older deployment may not
expose this tool. The unpublished legacy in-process remote profile remains restricted;
it does not gain a local routing oracle. The full native profile is unchanged.

## Bounds and reasoning evidence

- At most 256 subtasks and 4,096 dependency entries. DAG edges, cycles and references
  remain the native engine's responsibility. Inputs cannot supply `pesco_policy`,
  alpha allocation, local paths, verification commands or execution approval.
- The SDK defaults omitted `prefer_ensemble_singleton` to `false`. Explicit caller
  preferences remain respected. Replication advice never itself launches replication.
- `reason` explains the structural route. Optional `pesco.checks` records evaluated
  guards in order and stops at the first refusal. It is a decision trace, not private
  model chain-of-thought or an additional model call.
- A scope-matched local policy can additionally report aggregate panel counts,
  minimum log-evidence slack, known cost headroom and latency headroom. Unknown
  evidence stays null or absent. Tenant IDs, raw outcomes and group names are omitted.
- `execution_authorized`, `alpha_spent_by_route` and `is_correctness_proof` stay
  `false`. The public DTO rejects conflicting selected topologies or an affirmative
  authority/proof flag. Cost advice retains its separate estimate-only claim boundary.
- Without a qualified trusted-local policy, the existing route stays in place and
  `state` is `incumbent_no_policy`. Synthetic tests do not create a production policy.

## Native computational change

PESCO's fixed mixture, alpha schedule, cluster weighting and promotion rules are
unchanged. Repeated cluster differences reuse each betting factor while preserving
input order and `math.fsum` multiplicity. High-cardinality samples use the direct
factor path. Lower-bound inversion validates its sample once instead of on every
bisection step. These are computational improvements, not evidence of higher answer
accuracy or a new statistical guarantee.

The underlying boundaries are consistent with confidence-sequence and separate
calibration work, not a claim that either paper certifies this implementation:

- Howard et al., https://arxiv.org/abs/1810.08240
- Angelopoulos et al., https://arxiv.org/abs/2110.01052

## Authentication hardening and remaining limits

The native hosted MCP handler rejects repeated `Authorization` or `X-API-Key`
headers and requests carrying both credentials. A malformed bearer cannot fall back
to a valid secondary key. Both `/mcp` and `/v1/mcp` are covered. Credentials are
validated before tool dispatch, and refusal responses never echo them. This closes
credential-selection ambiguity; it is not evidence that an unauthenticated caller
could previously mint a valid key or access another tenant.

Offline tests exercise the actual hosted application, SDK HTTP transport, CLI
subprocess and thin MCP facade. No production probing, operator secrets, provider
calls, deployment, task creation or approval-state changes are needed. The installed
argihdrea read-only service was unhealthy during inspection; an argihdrea scan was
not run or represented as completed. Full penetration testing and deployed ingress
behavior remain unverified.

## Local verification, 2026-11-14

Base HEADs were public `6b7575e` and native `6ca3e11b0`, with pre-existing dirty work
in both trees. These results describe the uncommitted working trees, not those
commits alone. No commit, push or release was performed.

| Check | Observed result |
| --- | --- |
| Public packages suite | 1,186 passed, 4 skipped, exit 0 |
| Native PESCO/router/auth/security regression scope | 792 passed, exit 0 |
| Public mypy | 45 source files, exit 0 |
| Native mypy on five touched source files | exit 0 |
| Targeted Ruff, lock consistency, diff whitespace | exit 0 |
| Public wheel private-engine leakage gate | all four distributions passed, exit 0 |
| Native sdist/wheel | built, exit 0 |
| Public wheels under `python3 -I -S` | imported without private engine; route discovery present; unauthenticated route refused, exit 0 |
| Primary LSP | incomplete/inconclusive; not counted as clean |
| argihdrea scan | not run: configured service unhealthy |
| Production deployment/accuracy evaluation | not run |

Exact regression commands, from their respective checkout roots:

```sh
# Adaptorch-MCP
.venv/bin/python -m pytest packages --override-ini='addopts=' -q --tb=short
.venv/bin/mypy
uv lock --check --offline
.venv/bin/python scripts/check_public_wheels.py --package adaptorch adaptorch-client adaptorch-cli adaptorch-mcp

# adaptorch
.venv/bin/python -m pytest tests/test_pesco*.py tests/test_router.py tests/test_online_router.py tests/test_cascade_router.py tests/test_mcp_server.py tests/test_mcp_tenant_endpoint.py tests/test_mcp_routing_security.py tests/test_mcp_oauth.py tests/test_mcp_tenant_read_wiring.py tests/test_control_plane_authz.py tests/test_cloud_auth.py tests/test_security.py --override-ini='addopts=' -q --tb=short
.venv/bin/mypy src/adaptorch/pesco_statistics.py src/adaptorch/pesco_routing.py src/adaptorch/router.py src/adaptorch/mcp_server.py src/adaptorch/control_plane/__init__.py
uv build --no-build-isolation --out-dir /tmp/adaptorch-pesco-routing-20261114-dist
```

Public wheels for the isolated-import check are in
`/tmp/adaptorch-routing-wheels.Nc7t6s`. The first `--no-isolation` build attempt
failed because the root virtualenv has no `setuptools.build_meta`; the normal
isolated build then succeeded without installing build tools into the root or
system environment. A system `python3 -I -S` process loaded only the three wheel
paths plus the standard library, imported SDK/CLI/MCP, confirmed no `adaptorch`
engine was importable and verified the no-token route refusal. These temporary
artifacts are not a published release.

The native suite is a selected regression scope, not the entire engine repository.
The public suite reported a Starlette/httpx deprecation warning. No protection,
verifier, test exclusion or authentication fallback was weakened to obtain a pass.
Legacy tests explicitly requiring credential precedence now require rejection.
The initial expanded suites failed (2 public, 7 native); version expectations and
an omitted test-fixture argument were also corrected before the successful reruns.

A local microbenchmark compared the pre-change scalar formula with the new code,
using 25 alternating old/new timing trials and median wall time. Float results
were identical for these inputs:

| Input | Scalar reference | New | Reference/new |
| --- | --- | --- | --- |
| 1,000 repeated differences `(-1, 0, .25, 1) * 250` | 2.218 ms | 0.380 ms | 5.84x |
| 1,000 unique differences `i/500`, `i=-500..499` | 2.448 ms | 2.542 ms | 0.96x |
| Lower-bound inversion, 800 differences of `.1`, alpha `.05` | 128.563 ms | 11.552 ms | 11.13x |

These are local computational timings, not model reasoning speed or answer-quality
gains. Unique inputs were about 4% slower in this measurement. Reference-product,
null-expectation, endpoint/subnormal and independent R-oracle regressions remain
in the tested PESCO scope.

Proposed commit message, not executed:
`feat(routing): expose authenticated PESCO advice and reject ambiguous MCP credentials`

## Isolated release candidate

The release worktrees start from native `ce23502a68c16a2911a60cceff503229421dffa3`
and public `c897d625f1afb91ed948200baa85553b4326f841`, not the older dirty bases.
Unrelated audit/reveal/engine work is excluded. The already integrated smoke/BYOK
fixes and discovery descriptions remain intact. CLI and MCP advance to 0.1.7 and
0.6.2 so previously used versions are not overwritten; the client is 0.1.7.

Observed checks on the isolated sources, all exit 0:

- Public Ruff, strict mypy (44 source files), offline lock consistency and diff checks.
- Public tests: 1,197 passed, 4 skipped.
- All four public wheel leakage checks passed.
- Installed-wheel tests with `PYTHONPATH` unset: client 392 passed/2 skipped,
  CLI 143 passed, MCP 230 passed/6 skipped. Each wrapper resolved client 0.1.7.
- Native focused Ruff, strict mypy (10 source files), 561 selected regressions
  and sdist/wheel build passed. This excludes unrelated dirty-tree PESCO integrations.

The fresh public LSP probe confirmed three changed modules clean; the remaining
finding was a pre-Python-3.7 compatibility rule on `importlib.resources` in a package
requiring Python 3.11+, marked as a false positive without a source suppression.
The original dirty-checkout primary-LSP coverage remains unconfirmed.

The initial official dry run against old checkout SHA `6ca3e11b0` stopped because
that exact SHA had no successful CI. It sent no deployment. Production still needs
a separately verified integrated main SHA and the official release workflow;
local test/build results do not authorize bypassing that gate.

The unpublished workspace's maintainer engine pin and `uv.lock` now resolve to
`a8e07074a0e70ae6478b07eb90f90c1c94785814` (native PR #241). A fresh
`uv sync --all-packages --extra dev --group engine --locked` installed that Git
revision into the isolated virtualenv, not the editable sibling. Its PEP 610
`direct_url.json` commit ID was verified, followed by successful
`uv run --frozen make check` and offline lock verification. Credential-free real
stdio initialization/listing passed with exactly ten pinned core/route tools.

Retained public sdist/wheel artifacts: `/tmp/adaptorch-isolated-public.Z9iEj9`.
All four wheel gates and a `python3 -I -S` smoke passed: source bytes match the
candidate, SDK/CLI/MCP import without the private engine, routing discovery exists
and no-token routing is refused. Native local artifacts are in
`/tmp/adaptorch-isolated-native.lvel5z` and are never public PyPI artifacts.

Native PR CI did not start jobs: runs `43630721804` and `43630775198` were blocked
by GitHub's account-payment/spending-limit annotation. This is not a code-test
failure or a remote pass. No billing change, protection bypass, publication or
production deployment was performed.
