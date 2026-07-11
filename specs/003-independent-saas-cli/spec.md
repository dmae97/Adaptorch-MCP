# Feature Specification: Independent AdaptTorch SaaS CLI

**Feature**: `003-independent-saas-cli`
**Created**: 2026-07-11
**Status**: Approved by user-provided architecture

## Problem

`adaptorch` is the local reference-engine CLI and `adaptorch-mcp` is an MCP server entrypoint. A SaaS/User API client must not reuse either command or call one adapter through the other.

## Requirements

### R1 — Independent packages and command

Add standalone `adaptorch-client` and `adaptorch-cli` packages. The CLI exposes only `adaptorchctl`; `ado` is deferred. Neither package imports `adaptorch` or `adaptorch_mcp`.

### R2 — Shared User API client

The typed client owns authentication, URL/TLS policy, bounded HTTP transport, JSON parsing, public DTOs, and API error mapping. It supports capabilities plus Run submit/list/get/cancel, evidence show, and artifact list.

### R3 — Safe CLI boundary

Credentials come only from `ADAPTORCH_API_KEY`. The CLI must not accept token arguments or print credentials. Hosted HTTPS is the default; plaintext HTTP is allowed only for exact loopback hosts. POST submission sends an idempotency key and is never automatically retried.

### R4 — Stable automation contract

Machine output is deterministic JSON on stdout. Diagnostics use stderr. Exit codes distinguish usage, auth, not-found, conflict, quota/rate-limit, transient transport, failed/cancelled runs, and inconclusive results.

### R5 — User documentation

Produce a Korean user guide suitable for the AdaptTorch page, including installation, authentication, command examples, CI usage, security notes, and the current MVP/deferred boundary.

## Out of Scope

Token persistence/keyring, OAuth device flow, profiles, shell completion, `ado`, SSE watch/reconnect, artifact download, rich/table rendering, embedded local-core imports, MCP backend migration, root workspace/lockfile updates, hosted API implementation, and publishing.

## Acceptance

- Package-local tests pass without network access.
- `python -m adaptorch_cli --help` exposes `adaptorchctl` commands without importing MCP/core.
- Ruff and mypy pass for both new packages.
- Existing dirty MCP hardening files and `uv.lock` remain unchanged.
- `docs/adaptorchctl-usage.ko.md` exists and matches implemented behavior.
