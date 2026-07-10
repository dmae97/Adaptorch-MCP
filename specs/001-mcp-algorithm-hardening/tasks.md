# Tasks: MCP Algorithm Parity and Hardening

## Phase 1 — Evidence and Design

- [x] T001 Inspect parent algorithm/MCP and current wrapper contracts
  > role: explorer
  > deps: none
  > files: [`../src/adaptorch/router.py`, `../src/adaptorch/mcp_server.py`, `packages/adaptorch-mcp/src/adaptorch_mcp/`]
  > verify: full file reads and source references recorded in `plan.md`
  > gate: summary-present
  > risk: low

- [x] T002 Create project-local spec-kit and architecture contract
  > role: planner
  > deps: T001
  > files: [`.speckit/config.yaml`, `specs/constitution.md`, `specs/001-mcp-algorithm-hardening/`]
  > verify: `test -f .speckit/config.yaml && test -f specs/001-mcp-algorithm-hardening/tasks.md`
  > gate: file-exists
  > risk: low

## Phase 2 — TDD Implementation

- [x] T003 Write failing hardening tests
  > role: coder
  > deps: T002
  > files: [`packages/adaptorch-mcp/tests/test_hardening.py`]
  > verify: targeted pytest fails for missing hardening behavior
  > gate: command-pass
  > risk: low

- [x] T004 Implement hardened parent facade
  > role: coder
  > deps: T003
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/hardening.py`, `packages/adaptorch-mcp/src/adaptorch_mcp/response_policy.py`]
  > verify: `uv run pytest packages/adaptorch-mcp/tests/test_hardening.py -q`
  > gate: command-pass
  > risk: high

- [x] T005 Integrate CLI and HTTP app factory
  > role: coder
  > deps: T004
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/runtime.py`, `packages/adaptorch-mcp/src/adaptorch_mcp/cli.py`, `packages/adaptorch-mcp/src/adaptorch_mcp/server.py`]
  > verify: targeted wrapper and hardening tests pass
  > gate: command-pass
  > risk: high

- [x] T006 Add redacted diagnostics and documentation
  > role: coder
  > deps: T005
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/diagnostics.py`, `packages/adaptorch-mcp/README.md`]
  > verify: diagnostics and docs truth tests pass
  > gate: command-pass
  > risk: medium

## Phase 3 — Correctness Wall

- [x] T007 Run static, type, test, and build gates
  > role: qa
  > deps: T006
  > files: []
  > verify: `uv run ruff check . && uv run mypy packages/adaptorch-mcp/src && uv run pytest -q && uv build --package adaptorch-mcp`
  > gate: command-pass
  > risk: medium

- [x] T008 Perform independent security and compatibility review
  > role: reviewer
  > deps: T007
  > files: [`.omk/evidence/review-security.md`, `.omk/evidence/review-work-final.md`]
  > verify: final reports contain no unresolved high-severity finding
  > gate: file-exists
  > risk: high
