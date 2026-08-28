# Feature Specification: SDK-First Integration Surface

**Feature**: `004-sdk-first-integration`
**Created**: 2026-08-28
**Status**: Draft — not implemented
**Constitution**: [specs/constitution.md](../constitution.md) (§2 remote algorithm boundary, §4 additive and reversible, §6 honest claims)

## Problem

A programmatic consumer that wants AdaptOrch today is pointed at MCP. That is
the wrong default, and the measured surfaces show why.

`adaptorch-mcp` wraps the **local parent engine**: `hardening.py` imports
`adaptorch.n8n_connector`, so the package only works where the proprietary
parent runtime is installed. It carries no HTTP client to the control plane.
Its tool surface is tiered — `diagnostics.EXPECTED_CORE_TOOLS` holds nine
tools and `_FULL_ONLY_TOOLS` adds `adaptorch_get_traces` and
`adaptorch_route_topology`, which a remote tenant cannot reach at all.

`adaptorch-client` is the **hosted API** path. It declares `dependencies = []`,
so it installs anywhere Python 3.11+ runs, and its eight methods cover every
endpoint in `contracts/openapi/adaptorch-user-api.v1.yaml`:

| User API v1 endpoint | Client method |
| --- | --- |
| `GET /v1/capabilities` | `capabilities()` |
| `GET /v1/whoami` | `whoami()` |
| `POST /v1/runs` | `submit_run()` |
| `GET /v1/runs` | `list_runs()` |
| `GET /v1/runs/{run_id}` | `get_run()` |
| `PUT /v1/runs/{run_id}/cancel` | `cancel_run()` |
| `GET /v1/runs/{run_id}/evidence` | `get_evidence()` |
| `GET /v1/runs/{run_id}/artifacts` | `list_artifacts()` |

The two are **not duplicates of each other**. They are different execution
paths, and only one of them is reachable by an ordinary hosted tenant.

The cost of the current default is concrete. `open-multi-agent-kit` ships
`packages/adaptorch-wpl/src/adaptorch-client.ts`, a TypeScript wrapper that
models the *MCP tool surface*: it dispatches by tool-name string, it has no
transport implementation, and it advertises `adaptorch_get_traces` and
`adaptorch_route_topology` to callers who may be remote tenants that cannot
call them. To use it, a consumer must install the parent engine and run a
server process — to reach an API that is plain HTTPS.

Nothing here says MCP is wrong. MCP is the right surface for agent tool-calling
against a local engine. It is the wrong surface for a program that wants the
hosted API.

## Requirements

### R1 — SDK is the documented default integration path

`README.md`, `docs/tools.md`, and the package READMEs must present
`adaptorch-client` as the integration surface for programmatic consumers, and
`adaptorch-mcp` as the surface for agent tool-calling against a local engine.
Each document must state which runtime each path requires: the SDK needs only
Python 3.11+, and MCP needs the installed parent engine.

### R2 — Surface boundaries are stated where a reader chooses

Wherever the tool surface is listed, the tier must be listed with it. A reader
must not be able to learn that `adaptorch_route_topology` exists without also
learning that a remote tenant cannot call it. `docs/tools.md` is the canonical
list; other documents link to it rather than restating the names.

### R3 — Parity test binds the documents to the code

Add a test that fails when a document lists a tool that
`diagnostics.EXPECTED_CORE_TOOLS` plus `_FULL_ONLY_TOOLS` does not contain, or
omits one they do. The current documents drifted precisely because nothing
enforced this: a downstream consumer recorded "exactly 10 real tools" as a
fixed count in a source comment, while the server had moved to nine core plus
two full-only. `adaptorch_usage` (commit `90ff878`) is on `main` and in no
released tag, so the drift is reachable by anyone tracking `main` before it is
ever published. A count asserted in prose cannot hold; a test against the
engine's own tuples can.

### R4 — Client parity test binds the SDK to the OpenAPI contract

Add a test asserting that every path and method in
`contracts/openapi/adaptorch-user-api.v1.yaml` has a corresponding
`AdaptOrchClient` method, and that the client exposes no method claiming an
endpoint the contract does not define. Parity holds today; the test keeps it
holding.

### R5 — Downstream migration note

Publish the mapping a downstream TypeScript or Python consumer needs to move
from MCP tool names to SDK methods, including the three tools that have **no**
SDK equivalent because they are not in the hosted contract at all:
`adaptorch_server_metrics`, `adaptorch_plan_catalog`, and `adaptorch_usage`.
Recording that they are out of contract is the point; a consumer must not go
looking for a client method that cannot exist.

## Known compatibility limits

- `adaptorch_usage`, `adaptorch_plan_catalog`, and `adaptorch_server_metrics`
  are absent from User API v1. Whether they should become hosted endpoints is a
  separate contract decision and is not assumed here.
- `list_runs` still accepts only `status` and `project_id` (Spec 003). This
  specification does not widen it.
- Evidence and artifact response shapes remain typed projections of documented
  JSON; real hosted responses still require integration verification.

## Out of scope

- Removing, deprecating, or feature-gating `adaptorch-mcp`. It keeps its
  current behavior and support.
- Making the MCP server call the SDK. The two reach different systems; routing
  local engine calls through a hosted HTTP client would be a regression.
- Adding hosted endpoints for usage, plan catalog, or server metrics.
- Any change to `uv.lock` or root workspace configuration (constitution §4).
- Changes inside `open-multi-agent-kit`. The migration note is published here;
  acting on it belongs to that repository.

## Acceptance

1. A reader following `README.md` reaches a working hosted call without
   installing the parent engine or starting a server process.
2. Every document that names a tool also names its tier, and the R3 test fails
   when a name is added to one side only.
3. The R4 test fails when an OpenAPI path gains a method with no client
   counterpart.
4. Ruff, mypy, and pytest pass for both affected packages.
5. The 24 files already dirty in the working tree, and `uv.lock`, remain
   untouched by this work.
