# Changelog — adaptorch-mcp

All notable changes to the AdaptOrch MCP wrapper are documented here. The wrapper
delegates runtime behavior to the canonical `adaptorch` engine, so engine-level
accuracy work is surfaced here as activation/configuration, not duplicated logic.

## [0.5.0] - 2026-07-14

### Added
- `adaptorch_get_run` now advertises a closed MCP `outputSchema` and returns safe `structuredContent` alongside its legacy JSON text response.
- The default remote profile can expose the parent engine's bounded `correctness_wall` view, including verdict, blockers, advisories, evidence notes, and the non-authorizing claim boundary.

### Changed
- Bumped the standalone wrapper to `0.5.0` so the rebuilt artifact no longer collides with the released `0.4.2` code under the same version.
- Remote input descriptors and tool/resource responses are projected through explicit allowlists and fail closed on malformed parent contracts or unsupported nested output.

### Security
- Correctness Wall output is limited to sixteen 256-character entries per context list (covering the current parent contract), rejects proof/active-selector claims, and never exposes CEK records, selector scores, traces, diagnostics, or parent-provided structured side channels.
- The default remote surface remains eight tools; topology routing and trace oracles remain available only in the explicit `full` profile.

## [0.4.2] - 2026-07-11

### Changed
- Release pipeline only: GitHub Actions publishes with an environment-scoped PyPI token, authenticates the private core dependency during workspace install, and skips already-uploaded identical files. No wrapper runtime changes.

## [0.4.1] - 2026-07-11

### Changed
- Aligned the wrapper with the adaptor-page dashboard contract: documented the `ado_live_*`/`ado_test_*` (legacy `ak_*`) API-key story from `/app/api-keys`, and documented that engine-stamped `metadata.connector_source="mcp"` runs surface in the dashboard MCP status card and `/app/runs`.
- Diagnostics now report `formatRecognized` (boolean prefix check only) for the control-plane token so misconfigured credentials (for example a pasted dashboard JWT) are visible without exposing values.

## [0.4.0] - 2026-07-10

### Added
- Added a hardened MCP facade that continues to execute through the canonical parent AdaptOrch server/backend while defaulting to a strict remote tool/resource allowlist.
- Added regression coverage for exposure profiles, TLS/loopback policy, role-separated HTTP tokens, authenticated status endpoints, parent-tool compatibility, response redaction, and SSE event suppression.

### Changed
- Diagnostics now use `adaptorch_mcp.diagnostics.v2`: token presence remains visible, but token lengths are no longer reported; the payload also reports the active exposure profile, transport-policy validity, insecure-development opt-in, and honest algorithm-execution boundary.
- `adaptorch-mcp` and the HTTP app factory now use the hardened runtime instead of delegating directly to the parent CLI/factory.
- Split wrapper tests into focused modules to keep each touched test module below the repository's 250-pure-LOC review ceiling.

### Security
- The default `remote` profile hides local topology and trace oracles, blocks trace and verification-command controls, redacts algorithm-sensitive fields from all tool responses, suppresses MCP tool-event broadcasts, and disables sensitive run resources/completions.
- Remote control-plane HTTP is denied unless explicitly enabled for development; the MCP HTTP listener is loopback-only, status endpoints require bearer authentication, and the client-facing HTTP token must differ from the upstream token.
- Documented that these controls reduce exposure but cannot make distributed Python or black-box behavior impossible to reverse engineer.

## [0.3.0] - 2026-07-07

### Changed
- Re-pinned the delegated AdaptOrch engine dependency from `5b674a42` to `3a700afbb` in `uv.lock`, so the wrapper ships the latest engine algorithm surface (reproducibility beta, manifest canonical hash, router accuracy gate, quality-signal partial credit, configurable synthesis semantic weight, ensemble auto-preference).
- Removed public documentation and examples for the unsupported accuracy-profile preset surface (`ADAPTORCH_ACCURACY_PROFILE` and its four overrides); no shipped engine implements it.
- `docs/tools.md`: documented the two MCP prompts (`adaptorch_run_prompt`, `adaptorch_get_run_prompt`) and marked `adaptorch_cancel_run` as write/destructive.

### Added
- Documented installed-engine controls: `ADAPTORCH_REPRODUCIBLE`, `manifest_canonical_sha256`, `ADAPTORCH_ROUTER_ACCURACY_GATE`, `pass_rate_credit`/`quality_signal`, `ADAPTORCH_PAPER_SEMANTIC_WEIGHT`, `prefer_multi_model_ensemble_singleton`, and MCP `prefer_ensemble_singleton`.
- `tests/test_docs_truth.py` (fails if a phantom env symbol reappears or a documented `ADAPTORCH_*` is absent from the installed engine, and locks the publishing tag to the package version) and `tests/test_activation_surface.py`.

### Security
- Diagnostics now surface `ADAPTORCH_MCP_ALLOWED_ORIGINS` and guarantee `controlPlane.envError` never echoes a raw URL.

### Documentation
- Replaced benchmark-improvement claims with an honesty gate: publish improvement claims only with `n >= 50`, a Wilcoxon signed-rank test, and a 95% confidence interval.

## [0.2.1] - 2026-07-04

### Added
- Added redacted `controlPlane` diagnostics metadata so support output shows the default base URL, environment URL, resolved URL, source, and invalid-env status without printing token values.
- Added regression coverage for base-url normalization, invalid environment URLs, empty `--base-url=` fallthrough, `argv=None` behavior, and the local smoke default.

### Changed
- Changed default hosted control-plane base URL from `https://adaptorch.ai.kr` to `https://adaptorch.com` in `adaptorch_mcp.cli._HOSTED_BASE_URL`. Explicit `--base-url` and `ADAPTORCH_CONTROL_PLANE_BASE_URL` continue to take precedence; only the unset-fallback default changes.
- Hardened `adaptorch-mcp` base-url resolution: whitespace-only `ADAPTORCH_CONTROL_PLANE_BASE_URL` is treated as unset, valid environment URLs are trimmed before forwarding, invalid non-empty environment URLs raise `ValueError`, and empty `--base-url=` falls through to env/hosted defaults.
- Documented entrypoint-specific defaults: `adaptorch-mcp` falls back to the hosted control plane, while `adaptorch-mcp-smoke` intentionally keeps the local `http://127.0.0.1:8000` fallback.

### Security
- Redacted URL userinfo from diagnostics/config output and documented that base URLs must not embed credentials.

## [0.2.0] - 2026-06-20

### Added
- Expanded package and root documentation for stdio/HTTP execution, CLI command
  surfaces, environment variables, tool lists, doctor/smoke usage, example
  templates, publication checks, and security hygiene. These are documentation
  and example-template updates only; runtime defaults remain unchanged.

### Notes
- Historical note: this release documented an unsupported preset surface that is
  removed in `[Unreleased]`. Future improvement claims require `n >= 50`, a
  Wilcoxon signed-rank test, and a 95% confidence interval.

## [0.1.0]

### Added
- Initial installable MCP bridge delegating CLI + app factory to
  `adaptorch.mcp_server` (stdio + HTTP transports).
