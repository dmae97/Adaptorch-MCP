# Changelog — adaptorch-mcp

All notable changes to the AdaptOrch MCP wrapper are documented here. The wrapper
delegates runtime behavior to the canonical `adaptorch` engine, so engine-level
accuracy work is surfaced here as activation/configuration, not duplicated logic.

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
