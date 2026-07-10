---
description: "OMK Implementation Plan template with current agent routing and evidence gates"
---

# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**OMK Preset**: `omk`

## Summary

[One-paragraph summary of approach]

## Runtime Inventory

- **Harness**: [Path to `.omk/runs/<runId>/chat-agent-harness.json` if present, else "not present"]
- **MCP Scope**: [project | all | none]
- **Skills**: [Relevant skill names only]
- **Authority**: The OMK root coordinator is the sole final writer/merger.

## Agent Routing

<!--
  Use live OMK roles confirmed by runtime status.
  Match phase names to tasks.md phases for automatic routing.
-->

| Phase | Primary Role | Secondary Roles | Evidence Gate |
|-------|--------------|-----------------|---------------|
| Bootstrap | explorer | qa | file-exists |
| Design | architect | planner | file-exists |
| Core | coder | reviewer | command-pass |
| QA | qa | reviewer | command-pass |
| Integration | reviewer | qa | command-pass |

## Project Structure

```text
packages/adaptorch-mcp/
├── src/adaptorch_mcp/      # Typed package implementation
├── tests/                  # Unit and integration tests
├── README.md               # Package documentation
└── pyproject.toml          # Package and build contract

specs/{feature}/
├── spec.md                 # Requirements
├── plan.md                 # This file
└── tasks.md                # DAG-ready tasks

.omk/evidence/
├── verification.md         # Quality-gate output summary
└── security-review.md      # Security review when needed
```

## Complexity Check

| Concern | Decision | Rationale |
|---------|----------|-----------|
| New dependencies | [List or "none"] | [Why needed] |
| Breaking changes | [Yes/No] | [Migration plan if yes] |
| Parallel tasks | [Count] | [Which phases can run in parallel] |
| MCP/secret exposure | [None/Scoped] | [How secrets stay out of artifacts] |

## Quality Gates

- **Lint**: `uv run ruff check .` — static analysis
- **TypeCheck**: `uv run mypy packages/adaptorch-mcp/src` — strict Python checking
- **Secrets**: `gitleaks protect --staged --redact` — staged leak scan
- **Build**: `uv build --package adaptorch-mcp` — wheel and sdist
- **Tests**: `uv run pytest -q` — project test harness
- **Evidence**: store sanitized summaries under `.omk/evidence/`
