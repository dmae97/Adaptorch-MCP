# Changelog — adaptorch-mcp

All notable changes to the AdaptOrch MCP wrapper are documented here. The wrapper
delegates runtime behavior to the canonical `adaptorch` engine, so engine-level
accuracy work is surfaced here as activation/configuration, not duplicated logic.

## [Unreleased]

### Added
- Added redacted `controlPlane` diagnostics metadata so support output shows the default base URL, environment URL, resolved URL, source, and invalid-env status without printing token values.
- Added regression coverage for base-url normalization, invalid environment URLs, empty `--base-url=` fallthrough, `argv=None` behavior, and the local smoke default.

### Changed
- Hardened `adaptorch-mcp` base-url resolution: whitespace-only `ADAPTORCH_CONTROL_PLANE_BASE_URL` is treated as unset, valid environment URLs are trimmed before forwarding, invalid non-empty environment URLs raise `ValueError`, and empty `--base-url=` falls through to env/hosted defaults.
- Documented entrypoint-specific defaults: `adaptorch-mcp` falls back to the hosted control plane, while `adaptorch-mcp-smoke` intentionally keeps the local `http://127.0.0.1:8000` fallback.

### Security
- Redacted URL userinfo from diagnostics/config output and documented that base URLs must not embed credentials.

## [0.2.0] - 2026-06-20

### Added
- Documented the AdaptOrch **accuracy activation surface** (env-only, default
  off): `ADAPTORCH_ACCURACY_PROFILE` (`off` | `balanced` | `max_accuracy`) plus
  per-field overrides (`ADAPTORCH_PARTIAL_CREDIT_PREFER_CONFIDENCE`,
  `ADAPTORCH_JUDGE_OVERRIDE_MARGIN`, `ADAPTORCH_VERIFICATION_CRITICAL_COMMANDS`,
  `ADAPTORCH_VERIFICATION_CRITICAL_WEIGHT`). See `README.md` and
  `examples/mcp-http.env.example`.
- Expanded package and root documentation for stdio/HTTP execution, CLI command
  surfaces, environment variables, tool lists, doctor/smoke usage, example
  templates, publication checks, and security hygiene. These are documentation
  and example-template updates only; runtime defaults remain unchanged.

### Notes
- Tracks the AdaptOrch core accuracy line **P11–P19**: confidence-weighted /
  calibrated / robust self-consistency, answer-aware + partial-credit quality,
  semantic vote pooling, medoid selection, command-criticality weighting,
  logprob-aware confidence, agreement-adaptive ranking, router-threshold
  calibration, the unified `AccuracyProfile`, selection fusion, and the
  measured adopt-only-if-better gate (`accuracy_gate` / `accuracy_measurement`).
- Activation stays **opt-in per deployment**; the engine default profile remains
  `off`. A deterministic offline measurement (off=0.70, balanced=0.85,
  max_accuracy=1.00 on a 20-case representative corpus) justifies enabling a
  profile where appropriate; a live `execute_benchmark_run` on a real corpus is
  recommended before any global default flip.

## [0.1.0]

### Added
- Initial installable MCP bridge delegating CLI + app factory to
  `adaptorch.mcp_server` (stdio + HTTP transports).
