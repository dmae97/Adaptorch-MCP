# Feature Specification: MCP Algorithm Parity and Hardening

**Feature Branch**: `001-mcp-algorithm-hardening`
**Created**: 2026-07-10
**Status**: Approved for implementation by the user's explicit request
**Input**: Enhance this MCP using the parent repository's algorithm while hardening it against reverse engineering.

## Problem

The wrapper currently delegates to `adaptorch.mcp_server`, which preserves algorithm parity but also advertises a local topology oracle and permits security-sensitive transport defaults that operators can misuse. Python distribution and a queryable local oracle cannot provide absolute anti-reverse-engineering guarantees.

## Requirements

### R1 — Parent contract parity (P1)

**What**: Reuse the parent MCP server/backend rather than copying routing or synthesis algorithms. Fail closed if required parent MCP symbols or canonical tools are unavailable.
**Verify**: targeted compatibility tests pass with canonical and incomplete fake parent runtimes.

### R2 — Hardened algorithm exposure (P1)

**What**: Default to a remote exposure profile that withholds local topology and trace oracle tools. Preserve the full parent surface only through explicit operator opt-in.
**Verify**: `tools/list` omits sensitive tools by default, blocked `tools/call` returns JSON-RPC method-not-found, and full profile restores the canonical surface.

### R3 — Secure transport policy (P1)

**What**: Require HTTPS for non-loopback control-plane URLs by default. Permit HTTP only for loopback or explicit insecure-development opt-in.
**Verify**: URL policy tests cover HTTPS, loopback HTTP, remote HTTP rejection, credentials, and explicit opt-in.

### R4 — Token separation (P1)

**What**: HTTP MCP mode must use a client-facing token different from the upstream control-plane token. Compare without timing-leaky equality.
**Verify**: equal tokens fail before the server starts; distinct tokens pass.

### R5 — Redacted posture diagnostics (P2)

**What**: Diagnostics report exposure profile and security controls without token values or algorithm internals.
**Verify**: serialized and formatted diagnostics contain no supplied secret values.

### R6 — Documentation (P2)

**What**: Document the hardened default, full-profile opt-in, transport policy, and the non-guarantee boundary for reverse engineering.
**Verify**: docs truth tests pass.

## Expected Files

- `packages/adaptorch-mcp/src/adaptorch_mcp/hardening.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/response_policy.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/runtime.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/cli.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/server.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/diagnostics.py`
- `packages/adaptorch-mcp/tests/test_hardening.py`
- `packages/adaptorch-mcp/tests/test_hardened_runtime.py`
- `packages/adaptorch-mcp/tests/test_wrapper.py`
- `packages/adaptorch-mcp/tests/test_diagnostics_and_smoke.py`
- `packages/adaptorch-mcp/tests/test_activation_surface.py`
- `packages/adaptorch-mcp/tests/test_docs_truth.py`
- `packages/adaptorch-mcp/README.md`

## Out of Scope

- Claiming absolute prevention of source inspection or black-box model extraction.
- Copying parent routing/synthesis algorithms into this public wrapper.
- Changing the parent repository, package dependencies, or lockfiles.
- DRM, packers, native compilation, or third-party obfuscation dependencies.

## Acceptance

1. Hardened mode is default and fail-closed.
2. Full/local algorithm exposure requires explicit opt-in.
3. Parent algorithm remains the only implementation source.
4. Existing non-sensitive MCP tools remain available.
5. `uv run ruff check .`, `uv run mypy packages/adaptorch-mcp/src`, `uv run pytest -q`, and `uv build --package adaptorch-mcp` pass.
