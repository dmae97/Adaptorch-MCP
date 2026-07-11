# Implementation Plan: Independent AdaptTorch SaaS CLI

## Candidates

1. Extend `adaptorch-mcp` with user commands — rejected; adapter roles become coupled.
2. Reuse `adaptorch` — rejected; command and package ownership collide with the local engine.
3. **Selected**: independent `adaptorch-client` + `adaptorch-cli` packages with `adaptorchctl`.

## Minimal Vertical Slice

Use only the Python standard library. `adaptorch-client` implements secure JSON HTTP and typed service methods. `adaptorch-cli` handles env/config resolution, file input, deterministic JSON, and exit codes. No workspace or lockfile mutation is required for source-level validation.

## DAG

`spec -> contract/tests RED -> client + CLI GREEN -> usage docs -> narrow checks -> review -> result artifact`

## Owned Paths

- Client: `packages/adaptorch-client/**`
- CLI: `packages/adaptorch-cli/**`
- Contracts: `contracts/**`
- Docs: `docs/adaptorchctl-usage.ko.md`, root `README.md`
- Spec: `specs/003-independent-saas-cli/**`
- Goal evidence: `.omk/goals/adaptorchctl/result.json`

Existing modified paths under `packages/adaptorch-mcp/**`, `specs/002-remote-public-contract/**`, and `uv.lock` are forbidden.

## Verification

```bash
PYTHONPATH=packages/adaptorch-client/src:packages/adaptorch-cli/src uv run --no-sync pytest packages/adaptorch-client/tests packages/adaptorch-cli/tests -q
uv run --no-sync ruff check packages/adaptorch-client packages/adaptorch-cli
MYPYPATH=packages/adaptorch-client/src:packages/adaptorch-cli/src uv run --no-sync mypy --strict packages/adaptorch-client/src packages/adaptorch-cli/src
PYTHONPATH=packages/adaptorch-client/src:packages/adaptorch-cli/src uv run --no-sync python -m adaptorch_cli --help
git diff --exit-code -- uv.lock packages/adaptorch-mcp
```

## Stop Conditions

Stop if implementation requires credentials, network access, a lockfile edit, changes to current dirty MCP files, or invented hosted behavior beyond the supplied User API contract.
