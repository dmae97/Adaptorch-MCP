# MCP Tool Surface

The package delegates tool registration to `adaptorch.mcp_server`. The default `remote` profile exposes nine hardened tools. The two rows marked `full only` are available only with `ADAPTORCH_MCP_EXPOSURE_PROFILE=full`.

| Tool | Type | Purpose |
| --- | --- | --- |
| `adaptorch_run` | write | Submit an AdaptOrch task payload and optionally wait for terminal status. |
| `adaptorch_get_run` | read | Fetch a run summary plus an optional bounded Correctness Wall view by `run_id`. |
| `adaptorch_get_artifacts` | read | Fetch artifact metadata for a run. |
| `adaptorch_list_runs` | read | List recent control-plane runs. |
| `adaptorch_get_traces` | read/full only | Fetch execution traces for a run. |
| `adaptorch_cancel_run` | write/destructive | Request cancellation for an in-flight run. Keep manually approved. |
| `adaptorch_route_topology` | read/local/full only | Route a DAG locally through AdaptOrch's topology router and price the routed topology against the baseline. |
| `adaptorch_server_metrics` | read/local | Read redacted MCP server metrics. |
| `adaptorch_capabilities` | read/local | Read synthesis modes, topologies, extractors, verifier/VERA vocabularies, connectors, server features, and plan catalog. |
| `adaptorch_usage` | read | Read the calling tenant's usage window: plan level, period, used, limit, remaining, percentage. |
| `adaptorch_plan_catalog` | read/local | Read hosted plan catalog: Starter $0, Pro $39, Team $149. |

## Engine algorithm surface (delegated)

The wrapper never reimplements routing or synthesis. The values below are read from the
installed `adaptorch` engine and are asserted by
`packages/adaptorch-mcp/tests/test_engine_algorithm_parity.py`.

| Surface | Engine truth | Notes |
| --- | --- | --- |
| `synthesis_mode` (supported) | `paper`, `robust`, `robust_lite`, `stable_hybrid` | Distinct strategies executed by `adaptorch.synthesis`. Default is `robust`. |
| `synthesis_mode` (serving selection) | `auto` | The control plane selects an engine mode; `synthesis_mode_requested` and `synthesis_mode_used` remain visible in run responses. Not a fifth engine algorithm. |
| `synthesis_mode` (deprecated alias) | `fourier_aggressive` → `stable_hybrid` | Still accepted for compatibility; the engine resolves it to `stable_hybrid` and reports `mode_used`. |
| `model` (control-plane Auto) | `auto` | Supporting deployments resolve from tenant provider defaults or confirmed history and return `model` + `model_selection_source`. Provider/key still required; unresolved requests are rejected before admission. Not automatic task submission or provider-key discovery. |
| `output_extractor` | `final_answer`, `multiple_choice_letter` | Engine extractor modes. `none` requests no extractor and is not forwarded to the engine. |
| Topologies | `parallel`, `sequential`, `hierarchical`, `hybrid`, `multi_model_ensemble`, `multi_turn_debate` | Router-selectable topologies reported by `adaptorch_capabilities`. |
| Orchestration verdicts | `no_extra_spend`, `structural_spend`, `replication_unproven`, `replication_supported`, `replication_rejected` | Cost-vs-evidence verdicts from `adaptorch.orchestration_value`. |
| Orchestration actions | `proceed`, `measure_first`, `downshift` | Recommended caller actions. Advisory only — the engine never applies them. |
| Verifier types | `expected_answer_numeric`, `hard_v3_independent` | From `known_verifier_types()`. Discovery only; not a proof of correctness. |
| Verification outcomes | `PASS`, `FAIL`, `ENV_ERROR`, `CANDIDATE_ERROR`, `TIMEOUT`, `FLAKY`, `AMBIGUOUS`, `SKIPPED` | `VerificationOutcomeKind` values. |
| Verification decisions | `SHIP`, `REJECT`, `ABSTAIN`, `ESCALATE`, `INCONCLUSIVE_ENVIRONMENT` | `VerificationDecision` values. `SHIP` is not a release authorization. |
| Evidence causality | `CandidateCaused`, `EnvironmentCaused`, `Ambiguous`, `NotApplicable` | `EvidenceCausality` values. |

`adaptorch_capabilities` reports `synthesis_modes` (everything callers may pass),
`supported_synthesis_modes`, `deprecated_synthesis_mode_aliases`, `topologies`,
`output_extractor_modes`, `orchestration_value_verdicts`,
`orchestration_value_actions`, `verifier_types`, `verification_outcome_kinds`,
`verification_decisions`, and `evidence_causalities`. Older engines that omit those
fields still project cleanly.

## Orchestration cost advisory

Orchestration is not free, and this project ships no evidence that running the same
task more than once raises accuracy. `adaptorch_route_topology` therefore returns an
`orchestration_value` block next to the routing decision, so a caller can price the
decision **before** a run pays for it.

| Argument | Effect |
| --- | --- |
| `prefer_ensemble_singleton` | Routes single-node DAGs to `multi_model_ensemble` — the same flag `adaptorch_run` accepts, priced here first. `true` forces it on, `false` opts out explicitly, `null`/omitted leaves the auto policy in charge. |
| `model` | Adds USD estimates. An unpriced model reports `null` instead of a guessed price. |
| `measured_quality_gain` | Accuracy gain **you measured** for the routed topology versus the baseline. Never inferred. |
| `min_quality_gain` | The acceptance bar that gain must clear. You pay for the spend, so you own the bar. |

Cost comes from the engine's own topology cost profiles; the baseline is `sequential`.
Benefit is never asserted:

| Verdict | Meaning | Action |
| --- | --- | --- |
| `no_extra_spend` | The topology only orders work the run performs anyway. | `proceed` |
| `structural_spend` | Extra spend is coordination over distinct DAG work. | `proceed` |
| `replication_unproven` | Extra spend buys repeated attempts at the same work, with no measurement supplied. | `measure_first` |
| `replication_supported` | A supplied measurement clears the caller's bar. | `proceed` |
| `replication_rejected` | A supplied measurement misses the bar; the baseline buys the same result for less. | `downshift` |

Every advisory carries `claim_boundary`: `is_correctness_proof: false`,
`is_active_selector: false`, `is_cost_model_estimate: true`. It is a disclosure, not a
selector — routing is unchanged by it. Token and USD figures are cost-model estimates,
not billed amounts.

`adaptorch-mcp-doctor` reports the same surface under `algorithmSurface`:
`engineExportsOrchestrationValue`, `orchestrationValueParity`
(`match` / `drift` / `unavailable`), and `driftingFields`. An engine older than the
surface reads `unavailable` and stays OK; a genuine vocabulary mismatch reads `drift`
and fails the doctor closed.

## BYOK run admission

Provider credentials are process configuration, not part of the public `adaptorch_run` input schema. Set `ADAPTORCH_MCP_PROVIDER` and `ADAPTORCH_MCP_PROVIDER_MODEL` together, plus `ADAPTORCH_MCP_PROVIDER_API_KEY` for credentialed providers. The wrapper forwards them only as `X-Provider`, `X-Provider-Model`, and `X-Provider-Key` headers on `POST /v1/runs`.

The key is omitted from tool arguments, request bodies, non-run requests, repr output, and errors. A partial configuration fails before the server starts, and an installed engine without provider-credential support fails closed rather than silently sending an unauthenticated run.

Tenant Auto models require trusted selection storage on the control plane. The
current shared-store path rejects tenant/deployment model resolution before charging
until its schema supports that field; explicit models keep working without an
unpersisted source annotation. Caller-provided payload annotations are not selection evidence.

## Tenant usage awareness

Usage is scoped by the `ADAPTORCH_CONTROL_PLANE_TOKEN` you configure. The control plane
resolves the tenant from that key, so `adaptorch_usage` takes **no arguments** and a
client cannot ask for another tenant's numbers — an extra argument is rejected with
JSON-RPC `-32602`.

| Field | Meaning |
| --- | --- |
| `tenant_id` | Your own tenant, as resolved from the key |
| `plan_level` | Plan the limit came from (`starter`, `pro`, `team`) |
| `period` | UTC billing period the counter belongs to |
| `used` / `limit` / `remaining` | Run counter for the period (`limit` may be unlimited) |
| `usage_percentage` | `used / limit` as a percentage |

The wrapper projects only those fields; counter sources, database rows, and any other
control-plane internals are dropped.

When a run is rejected because the period counter is exhausted, the tool result is an
error payload rather than a masked internal failure:

```json
{
  "error": "QUOTA_EXCEEDED",
  "message": "Tenant quota exhausted for the current period",
  "usage": { "limit": 1000, "used": 1000, "remaining": 0, "upgrade_url": "/pricing" }
}
```

The wrapper's safe backend makes one HTTP attempt, including quota, burst-limit and
transient failures. It never blindly retries a POST or follows redirects. Parent
n8n consumers outside this wrapper retain their own retry policy. Quota errors keep
validated usage counters and a fixed public message, not private operator text.

## Structured run output

Run/create/get/cancel/list projections preserve `synthesis_mode_requested`,
`synthesis_mode_used`, and `auto_synthesis_reason` when supplied by the parent.
The `used` field is admission/collection metadata, not proof of the final engine
mode. `status` is liveness; `result_status`, `evaluation_status` and
`score_validity_status` remain separate. Missing fields stay missing/null.

`consistency` must be a finite 0–1 number or null; `duration_ms` a nonnegative
integer or null. Subject-bound readers reject another run's response. Duplicate
JSON keys, malformed error flags and non-finite JSON fail closed. Error results do
not populate the successful run's structured output schema.

In the remote profile, `adaptorch_get_run` advertises a closed MCP `outputSchema` and returns both the legacy JSON text block and an equivalent safe `structuredContent` mapping. When the installed AdaptOrch control plane provides `correctness_wall`, the wrapper projects only bounded verdict, blocker, advisory, evidence-note, recommendation, and claim-boundary fields. A `PASS` verdict is evidence-gate observability only—not a correctness proof, active-selector decision, Full50 GO result, or authorization to apply a candidate.

## Consumer run receipt

`correctness_wall` answers an auditor. `first_run_receipt` answers the person who
paid for the run: did it work, did it stay inside the budget cap, was it verified.
The projection is available when the parent payload actually includes it; this is
not proof that a given REST deployment forwards it. Missing parent fields stay
missing, and explicitly null or malformed receipts project as `null`.

| Field | Values |
| --- | --- |
| `verdict` | `OK`, `DEGRADED`, `FAILED` |
| `budget_state` | `within_cap`, `cap_missing`, `cap_untrusted`, `cost_unknown`, `cap_exceeded` |
| `verification_state` | `passed`, `failed`, `not_run`, `error` |
| `claims` | `state` (`beta_only`), `positioning`, and three flags that are always false: `b2c_launch_ready`, `full50_claimed`, `official_correctness_claimed` |

The receipt is built from the user's own prompt and is persisted beside a server
artifact path and a keyed digest. None of that crosses the API boundary: the
wrapper projects the four fields above and drops everything else, including
`artifact_path`, `prompt_sha256`, `prompt_hmac_sha256`, and the redacted preview.

A receipt whose claim flags are not all false is projected as `null` rather than
forwarded — a beta must not tell a paying consumer it is launch-ready. A malformed
receipt nulls the same way and leaves the rest of the run summary intact, so a
client still sees status without receiving an unvalidated verdict.

## Resources and templates

The installed engine exposes four static resources and two run resource templates.
The default remote facade exposes only server-info and cloud plans; the other
resources and run templates require the explicit full profile.

| URI | Type | Purpose |
| --- | --- | --- |
| `adaptorch://tools` | resource/full only | Tool registry summary. |
| `adaptorch://connectors` | resource/full only | Available connector names. |
| `adaptorch://server-info` | resource | Protocol and server metadata. |
| `adaptorch://plans/cloud` | resource | Hosted cloud plan catalog. |
| `adaptorch://runs/{run_id}/summary` | template/full only | Run summary resource template. |
| `adaptorch://runs/{run_id}/artifacts` | template/full only | Run artifacts resource template. |

## Prompts

| Prompt | Purpose |
| --- | --- |
| `adaptorch_run_prompt` | Template for calling `adaptorch_run` with a task prompt, optional context, and synthesis mode. |
| `adaptorch_get_run_prompt` | Template for calling `adaptorch_get_run` by `run_id`. |

## Public Verification

[The client contract record](2026-09-08-algorithm-client-contract.md) distinguishes
these source changes from a release, and the SDK's reported schema/build versions
from hosted inference-tape support.

Use the smoke command after installation:

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.com
```

The smoke command checks `initialize`, `tools/list`, and the expected core tool subset without printing token values. It is a subset smoke, not a full surface conformance test. Add repeatable `--expected-tool <name>` flags when validating a specific hosted/core release.

## Auto-approve guidance

For trusted local clients, auto-approve only tools whose outputs are safe for that client. Keep `adaptorch_run` and `adaptorch_cancel_run` manually approved. For shared or production clients, avoid auto-approving run, artifact, and trace readers unless those payloads are already sanitized.
