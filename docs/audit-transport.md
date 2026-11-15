# Optional audit-only transport

The hosted service must explicitly enable its audit service. Only its returned
`tools/list` advertises these tools; the wrapper's offline discovery catalog does
not invent availability:

- `adaptorch_audit(request_json, idempotency_key)` queues an audit-only request.
- `adaptorch_get_audit(audit_id)` reads tenant-scoped status and bounded ledger.
- `adaptorch_get_audit_artifact(audit_id, kind, page_bytes=4096, cursor=null)` reads
  immutable `request`, `candidates` or `validation` JSON as UTF-8 byte pages.

`request_json` uses `audit.submission.v1`. It includes task/turn, task criteria,
non-goals, supplied snapshot, anchors/evidence and collector scope. It cannot
select tenant/actor/audit identity, execution commands, budgets or models, or
attest client-provided runtime execution as a host observation. It is not a
repository attestation. The service derives identity from the authenticated
credential and checks current membership for user-owned keys and JWT subjects.
Keep the same key and payload after an uncertain admission; a changed payload
under the same key is a conflict. A queued request is not a completed audit.

`audit_tool_contracts.json` is exported from the core's opt-in DTO schemas. This
wrapper imports no engine code. An upstream audit input/output/annotation
contract that differs from that pinned snapshot fails closed. New optional
fields require an explicit snapshot refresh and parity tests, not a permissive
raw passthrough. Return projections preserve `outputSchema` and generate identical
JSON text/`structuredContent`, validate bounded types, and bind returned audit IDs
to requested IDs. Provider credentials are never attached to these tool calls.

Status `COMPLETED` describes processing, not correctness or release approval.
Read `validation_state` and `is_current`; empty findings and reference validity
are not a pass. Read all pages using `next_cursor` with the same audit, kind and
page size. Compare total bytes/full hash if reconstructing an artifact. A cursor
expires and cannot be moved to another tenant, audit, snapshot or artifact.
`candidates` is untrusted model text, not an execution plan. No audit result grants
patch, command, replan, provider/model-switch or release authority.

Local changes only: neither this wrapper nor a service was deployed or published.
No paid inference was used. Core SQLite tests and fake DB-API tests do not verify
live PostgreSQL/RLS, production worker scheduling or reviewer quality. Actual
browser/HMR verification remains blocked in the paired core checkout.

To refresh from a sibling core checkout, review the DTO changes, run:

```sh
../adaptorch/.venv/bin/python ../adaptorch/scripts/export_audit_mcp_contract.py \
  --output packages/adaptorch-mcp/src/adaptorch_mcp/audit_tool_contracts.json
```

Run the core `test_audit_p2_contract.py` parity check with both checkouts and this
package's `test_audit_remote.py`, response-policy and discovery regressions.
