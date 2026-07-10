---
description: "OMK Task list template with execution metadata for DAG conversion"
---

# Tasks: [FEATURE NAME]

**Input**: Design documents from `/specs/[###-feature-name]/`
**Prerequisites**: plan.md (required), spec.md (required)
**Output**: OMK DAG-ready task list with execution metadata

## Format

Each task MUST include OMK Execution Metadata:

```txt
- [ ] T001 [P] Description with exact file paths in `backticks`
  > role: [explorer | planner | architect | coder | reviewer | qa]
  > deps: [comma-separated task IDs, or 'none']
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/file.py`, `packages/adaptorch-mcp/tests/test_file.py`]
  > verify: `uv run pytest packages/adaptorch-mcp/tests/test_file.py -q`
  > gate: [file-exists | command-pass | diff-nonempty | summary-present]
  > risk: [low | medium | high]
```

### Legend
- **[P]**: Can run in parallel (different files, no dependencies)
- **role**: Live OMK role confirmed by runtime status
- **deps**: Explicit dependencies. OMK scheduler uses these for topological ordering.
- **files**: Expected output files. OMK evidence gate checks these after execution.
- **verify**: Command to run after task completion. OMK runs this as a command-pass gate.
- **gate**: Evidence gate type that proves task completion.
- **risk**: If high, OMK requires an explicit checkpoint before this task.

---

## Phase 1: Bootstrap

**Purpose**: Project scaffolding and agent context loading

- [ ] T001 [P] Load project context, current harness, and existing codebase structure
  > role: explorer
  > deps: none
  > files: [`.omk/evidence/explore-summary.md`]
  > verify: `test -f .omk/evidence/explore-summary.md`
  > gate: file-exists
  > risk: low

- [ ] T002 [P] Verify toolchain scripts and runtime scopes
  > role: qa
  > deps: none
  > files: [`.omk/evidence/toolchain-summary.md`]
  > verify: `uv run ruff check . && uv run mypy packages/adaptorch-mcp/src`
  > gate: command-pass
  > risk: low

---

## Phase 2: Design & Planning

**Purpose**: Architecture decisions before any code change

- [ ] T003 Produce implementation plan with file-level breakdown
  > role: planner
  > deps: T001
  > files: [`specs/[###-feature-name]/plan.md`]
  > verify: `grep -c "##" specs/[###-feature-name]/plan.md`
  > gate: file-exists
  > risk: low

- [ ] T004 Define public API contracts and types
  > role: architect
  > deps: T003
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/contracts.py`]
  > verify: `uv run mypy packages/adaptorch-mcp/src`
  > gate: file-exists
  > risk: medium

---

## Phase 3: Core Implementation

**Purpose**: Build the feature slice by slice

- [ ] T005 [P] Implement domain models and data layer
  > role: coder
  > deps: T004
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/models.py`]
  > verify: `uv run pytest packages/adaptorch-mcp/tests -q -k models`
  > gate: command-pass
  > risk: medium

- [ ] T006 [P] Implement service / business logic layer
  > role: coder
  > deps: T005
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/services.py`]
  > verify: `uv run pytest packages/adaptorch-mcp/tests -q -k services`
  > gate: command-pass
  > risk: medium

- [ ] T007 Implement API / CLI / UI presentation layer
  > role: coder
  > deps: T006
  > files: [`packages/adaptorch-mcp/src/adaptorch_mcp/cli.py`]
  > verify: `uv run ruff check packages/adaptorch-mcp && uv run mypy packages/adaptorch-mcp/src`
  > gate: command-pass
  > risk: high

---

## Phase 4: Quality Assurance

**Purpose**: Parallel verification pipeline

- [ ] T008 [P] Write or update regression tests for all new modules
  > role: coder
  > deps: T005, T006, T007
  > files: [`packages/adaptorch-mcp/tests/test_[feature].py`]
  > verify: `uv run pytest packages/adaptorch-mcp/tests/test_[feature].py -q`
  > gate: command-pass
  > risk: low

- [ ] T009 [P] Run static analysis, type checking, and secret scan
  > role: qa
  > deps: T007
  > files: []
  > verify: `uv run ruff check . && uv run mypy packages/adaptorch-mcp/src && gitleaks protect --staged --redact`
  > gate: command-pass
  > risk: low

- [ ] T010 Review security and trust-boundary impact
  > role: reviewer
  > deps: T007
  > files: [`.omk/evidence/security-review.md`]
  > verify: `grep -Ei "risk|vuln|exposure|secret|none" .omk/evidence/security-review.md`
  > gate: file-exists
  > risk: high

---

## Phase 5: Integration & Delivery

**Purpose**: Merge-ready validation

- [ ] T011 Run full quality gate and evidence verification
  > role: qa
  > deps: T008, T009, T010
  > files: []
  > verify: `uv run pytest -q && uv build --package adaptorch-mcp`
  > gate: command-pass
  > risk: medium

- [ ] T012 Produce merge summary and evidence handoff
  > role: reviewer
  > deps: T011
  > files: [`.omk/evidence/merge-summary.md`]
  > verify: `grep -c "## Summary" .omk/evidence/merge-summary.md`
  > gate: file-exists
  > risk: low

---
