# Implementation Plan: Remote Public Contract Projection

## Candidates

1. Keep denylist and add more keys — rejected; channels remain open.
2. Selected: project the existing parent descriptor and JSON-RPC response envelope.
3. Define tool-specific public Pydantic models — deferred until hosted API contracts stabilize.

## Design

Reuse the parent schemas, remove the two explicitly blocked run fields, retain `additionalProperties: false`, and enforce projected top-level property names before delegation. Rebuild remote tool-call responses from a small safe envelope rather than copying parent mappings.

## DAG

`audit -> RED tests -> schema projection -> response projection -> targeted verify -> full package gates`

## Files

- `packages/adaptorch-mcp/src/adaptorch_mcp/hardening.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/public_schema.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/output_schema.py`
- `packages/adaptorch-mcp/src/adaptorch_mcp/response_policy.py`
- `packages/adaptorch-mcp/tests/test_hardening.py`
- `packages/adaptorch-mcp/tests/test_parent_contract.py`
- `packages/adaptorch-mcp/tests/test_response_policy.py`

## Stop Conditions

Stop if parent tool descriptors are malformed, the full profile changes, algorithms must be copied, or dependency/lockfile changes become necessary.
