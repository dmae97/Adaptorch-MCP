# Feature Specification: Remote Public Contract Projection

**Feature Branch**: `002-remote-public-contract`
**Created**: 2026-07-11
**Status**: Approved by delegated user judgment

## Problem

The remote facade blocks sensitive run arguments at execution time but still advertises them in `tools/list`. Tool responses sanitize algorithm-sensitive keys only inside JSON text while leaving other MCP response channels untouched.

## Requirements

### R1 — Projected remote input schema

Remote `adaptorch_run` must omit `trace` and `verification_commands`. Tool calls must reject top-level arguments outside the projected schema.

### R2 — Fail-closed response envelope

Remote tool responses may expose only sanitized JSON text content and boolean `isError`. Unexpected response channels and `error.data` must not cross the facade. Non-JSON text must become a generic tool error.

### R3 — Parent delegation

Routing, synthesis, and control-plane execution remain implemented only by the parent AdaptOrch package. Full exposure profile behavior remains unchanged.

## Out of Scope

OAuth, Streamable HTTP rewrite, hosted API decoupling, idempotency, control-plane state, billing, runner, CEK, dependencies, and lockfiles.

## Acceptance

Targeted tests demonstrate the leak before implementation and pass afterward. Ruff, mypy, package tests, and package build pass with no secret leak or parent-repository edit.
