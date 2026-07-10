---
description: "OMK Feature Specification template with agent-oriented requirements"
---

# Feature Specification: [FEATURE NAME]

**Feature Branch**: `[###-feature-name]`
**Created**: [DATE]
**Status**: Draft
**Input**: User description: "$ARGUMENTS"
**OMK Preset**: `omk` (DAG-optimized, parallel-agent ready)

## Agent-Oriented Requirements

<!--
  Write requirements as tasks an agent can execute.
  Each requirement should be verifiable by an evidence gate.
  Use live OMK roles confirmed by runtime status.
-->

### Requirement 1 - [Brief Title] (Priority: P1)

**Agent**: coder / architect
**Skills**: [Relevant configured skills, e.g. programming, security-review]
**MCP**: [Configured server such as understand-anything, or none]
**Evidence Gate**: file-exists + command-pass
**Risk**: medium

**What**: [Describe what the agent should build]
**Verify**: [How OMK checks completion — exact command or file path]

**Acceptance**:
1. File `packages/adaptorch-mcp/src/adaptorch_mcp/xxx.py` exists and exports `yyy`
2. Running `uv run pytest packages/adaptorch-mcp/tests/test_xxx.py -q` passes
3. Running `uv run ruff check packages/adaptorch-mcp` reports no errors

---

### Requirement 2 - [Brief Title] (Priority: P2)

**Agent**: coder
**Skills**: [Relevant skill names]
**Evidence Gate**: command-pass
**Risk**: low

**What**: [Describe]
**Verify**: [How OMK checks]

---

## Expected Files

<!--
  List all files the agent is expected to create or modify.
  OMK uses these for evidence gates.
-->

- `packages/adaptorch-mcp/src/adaptorch_mcp/[module].py` — [purpose]
- `packages/adaptorch-mcp/tests/test_[module].py` — [test coverage]
- `packages/adaptorch-mcp/README.md` — [documentation]

## Verification Commands

<!--
  Keep commands fast, deterministic, and safe for agents.
-->

- `uv run ruff check .` — static analysis
- `uv run mypy packages/adaptorch-mcp/src` — strict type checking
- `uv run pytest -q` — test harness
- `gitleaks protect --staged --redact` — staged secret scan before commit
- `uv build --package adaptorch-mcp` — package build

## Assumptions

- [Assumption about environment]
- [Assumption about existing code]
- [Assumption about MCP/skills scope]
