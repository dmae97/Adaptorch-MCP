# Implementation Plan: MCP Algorithm Parity and Hardening

**Branch**: `001-mcp-algorithm-hardening` | **Date**: 2026-07-10 | **Spec**: `spec.md`

## Algorithm Candidates

1. **Thin remote rewrite** — remove the parent package and implement a standalone MCP-to-control-plane gateway. Best distribution secrecy, but it changes dependencies/lockfiles and duplicates a large protocol surface.
2. **Hardened parent facade** — instantiate the canonical parent backend/server, filter algorithm oracle tools by default, and add transport/token guards in the wrapper. Preserves parity with the smallest reversible diff.
3. **Obfuscation/native packing** — package Python as an opaque artifact. Rejected: it does not prevent reverse engineering and creates a false security claim.

## Selected Design

Select candidate 2. The wrapper remains an adapter over the parent MCP implementation, so routing uses the parent's structural DAG features (`routing-dag-features.v2`), topology choices, synthesis modes, and control-plane execution. The hardened profile reduces queryable algorithm detail without forking those algorithms.

## Dependency DAG

`spec-kit → parent/current inspection → security tests (RED) → hardened facade → CLI/server integration → diagnostics/docs → full verification → security review`

## Runtime and Scope

- Parent repository: read-only reference only.
- Write scope: this repository's spec-kit plus `packages/adaptorch-mcp` source/tests/docs.
- New dependencies: none.
- Lockfile changes: none.
- Media assets: none; `omk-design-media` has no applicable artifact in this backend-only change.

## Security Model

- Default exposure profile: `remote`.
- Sensitive local tools: topology routing and execution traces.
- Remote profile: strict tool/resource allowlists, run-diagnostics redaction, no completions, no trace/verification-command input, and no SSE tool-event broadcast.
- Full profile: explicit `ADAPTORCH_MCP_EXPOSURE_PROFILE=full`.
- Non-loopback control-plane HTTP: rejected unless explicit insecure-development opt-in.
- MCP HTTP listener: exact loopback bind only; health and metrics require bearer authentication.
- HTTP transport: upstream and client-facing bearer tokens must differ.
- Remaining risk: installed Python dependencies and black-box output behavior can still be inspected.

## Verification

1. `uv run pytest packages/adaptorch-mcp/tests/test_hardening.py -q`
2. `uv run ruff check packages/adaptorch-mcp/src packages/adaptorch-mcp/tests`
3. `uv run mypy packages/adaptorch-mcp/src`
4. `uv run pytest -q`
5. `uv build --package adaptorch-mcp`

## Stop Conditions

- Required parent MCP public symbols are absent and no compatible facade can be built without copying the algorithm.
- A change would require a lockfile/dependency update.
- Existing dirty files would need destructive overwrite.
- Verification repeatedly fails outside owned paths.
