# 2026-09-13 source integration

The pending SDK/MCP work was integrated over published-wrapper commit `1a9cfa3`,
without republishing version 0.5.1. The source engine pin and uv lock now identify
`39bfeadd96e19348a6a98a1e3c7167c23f17e579`. No provider, account, quota or billing
operation was performed against a live service. Tests used loopback HTTP fixtures
and a network guard that rejects external sockets.

## Compatibility retained

- `ProviderCredential` is implemented once and remains importable from both the
  package root and `config`. The legacy `.headers` property is retained; only the
  dedicated POST credential path may actually forward provider headers.
- Hosted artifact-map keys remain available as named `items`; raw references are
  additionally preserved in `artifact_urls`. No download, hash or size is inferred.
- Remote run projections retain `model_selection_source` and serving-only `auto`.
- Verifier vocabularies are projected only if advertised by the installed engine.
  Importable research symbols do not invent a supported capability.
- The 0.5.1 Python range, independent launcher and `<0.2` engine dependency cap
  remain unchanged. SPDX license metadata identifies ClassicMate and includes the
  canonical license. These source changes do not overwrite PyPI metadata.
- Oversized numeric cost advisories fail closed instead of raising an overflow.

## Verification

| Check | Result |
| --- | --- |
| SDK/CLI isolated staged-tree tests | passed; staged implementation and tests together |
| Integrated package tests, Python 3.12 | 892 passed, 2 skipped before the final three overflow cases |
| `uv sync --frozen --all-packages --extra dev` in a new isolated environment | exit 0; exact locked engine installed |
| Exact-lock Python 3.11 tests including overflow regression | **895 passed, 2 skipped; exit 0** |
| Exact-lock Ruff | exit 0 |
| Exact-lock mypy | 37 source files, exit 0 |
| Exact-lock doctor | exit 0; no live run |
| Four public wheel builds/gate | exit 0; existing warning for in-process MCP engine dependency remains |
| Staged-diff secret scan | exit 0 |

Skips cover optional engine functionality, including the unavailable ModelStudio
provider. The conditional ModelStudio document is not a claim that the pinned
engine or hosted service currently supports it.

## Deliberately not merged

The pending stricter `scripts/check_public_wheels.py` policy and its new
`test_public_distribution_boundary.py` reject the existing in-process wrapper.
That conflicts with the published 0.5.1 distribution and current CI/release policy.
They are preserved separately for a distribution decision, rather than weakening
that proposed policy or silently blocking the current release workflow.

The original dirty checkout is preserved during integration. Reversible local
backups and full command evidence live under
`/tmp/adaptorch-commit-20260913-dvmkylvo/`. No tags, PyPI publication or manual
production deployment are part of this source push.
