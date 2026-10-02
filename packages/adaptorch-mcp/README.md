# AdaptOrch MCP client 0.6.0 candidate

This unreleased candidate is a remote-only, stdio-only policy bridge to authenticated
`POST /mcp`. It does not include, import, install, or execute the private AdaptOrch
engine. The only runtime dependency is the publicly published `adaptorch-client==0.1.2`.
No publication, production connection, or provider execution is implied by offline tests.

## Install and launch

After a separately approved release, install the published `adaptorch-mcp==0.6.0`.
For this candidate, install the locally built wheel and its public SDK dependency.
Python 3.11 and 3.12 are supported; both are covered by the candidate offline gates.

```sh
export ADAPTORCH_CONTROL_PLANE_TOKEN='<tenant-api-key>'
export ADAPTORCH_MCP_PROVIDER='openai'
export ADAPTORCH_MCP_PROVIDER_MODEL='<model>'
export ADAPTORCH_MCP_PROVIDER_API_KEY='<provider-key>'
adaptorch-mcp-client --base-url https://adaptorch.com
```

The four environment names above preserve the existing hosted connection guide.
`ADAPTORCH_API_KEY` is a lower-priority tenant-key fallback only.
`--base-url` takes precedence over `ADAPTORCH_CONTROL_PLANE_BASE_URL`, then the hosted default.
Tenant keys beginning `ado_` use `X-API-Key`; other configured tokens use Bearer.
Whether a key is accepted is decided by the hosted service, never by local validation.

An explicit `ADAPTORCH_MCP_PROVIDER_AUTH_TYPE=oauth` plus
`ADAPTORCH_MCP_PROVIDER=openai_codex` can use an access token in the same provider-key
slot; `ADAPTORCH_MCP_PROVIDER_ACCOUNT_ID` is optional. Provider configuration must
be complete. No ambient `OPENAI_API_KEY` or other provider environment is searched.
Credentials are process-local, excluded from repr/output, and never saved to disk.

## Supported command line

- `--base-url ORIGIN`: HTTPS origin only, with no credentials, path, query, or fragment
- `--transport stdio`: the sole transport
- `--stdio-framing line|newline|content-length`: line-delimited JSON by default; `newline` is a compatibility alias for `line`, with explicit MCP Content-Length also supported
- `--timeout SECONDS`: finite positive timeout up to 300 seconds, default 30
- `--allow-loopback-http`: development-only opt-in for exact localhost, 127.0.0.1, or ::1
- `--version`, `--help`: offline and token-free

`python -m adaptorch_mcp` is equivalent to `adaptorch-mcp-client`.
`adaptorch-mcp-doctor --json` runs offline without a key; `--strict` requires a key.
`adaptorch-mcp-smoke` defaults to the explicit launcher and performs authenticated
initialize/discovery only. Do not run a live smoke without authorization for that tenant.

## Nine tools and boundaries

The client validates the upstream inventory but exposes only:

1. `adaptorch_run`: hosted submission; configured provider headers only here
2. `adaptorch_get_run`: subject-bound run summary, closed structured output
3. `adaptorch_get_artifacts`: subject-bound validated references, no downloads
4. `adaptorch_list_runs`: limit 1–100, optional status
5. `adaptorch_cancel_run`: explicit destructive write
6. `adaptorch_server_metrics`: genuine client-process counts/latencies
7. `adaptorch_capabilities`: hosted discovery with unsupported features disabled
8. `adaptorch_usage`: authenticated tenant usage, no tenant override
9. `adaptorch_plan_catalog`: projected hosted catalog

Run inputs are a fixed, locally validated subset of the advertised contract:
`prompt`, `payload`, `context`, `connector_name`, `synthesis_mode`, `model`,
`budget_policy`, `wait_for_terminal`, `timeout_seconds`, `poll_interval_seconds`,
`ensemble_members` (2–5), `output_extractor`, and `prefer_ensemble_singleton`.
Optional fields absent upstream are hidden. Unknown arguments fail closed.

`wait_for_terminal` defaults upstream to true, with a 120-second wait unless configured.
The client request timeout is independently 30 seconds by default. For a long task,
explicitly submit with `wait_for_terminal: false`, retain the returned run ID, and use
`adaptorch_get_run`; or set appropriate explicit bounded wait and request timeouts.
An observer timeout does not prove the submission failed.

Idempotency and `resume_run_id` are unavailable in this hosted MCP version and are
hidden/rejected explicitly. The client never silently switches to REST, replays an
ambiguous write, cancels a run on timeout, or recommends unsupported replay/resume.
A timeout/error retains known run identity and uncertainty, never `new_run_safe: true`.

Tools are not auto-approved by examples. Submitting or cancelling can have consequences;
the host client should obtain appropriate user approval.

## Resources, prompts and lifecycle

Only `adaptorch://server-info` (local client lifecycle) and `adaptorch://plans/cloud`
(projected hosted catalog) are exposed. Resource templates/subscriptions/list-change
support and completions are disabled. The two known prompt templates are exposed only
after validating upstream inventory and bounded text-only response shapes.
Notifications are suppressed; `notifications/cancelled` cannot cancel a hosted run.
Shutdown and exit affect only this process, never the hosted singleton.

## Security and deadline semantics

Every upstream request uses the one configured origin and tenant credential.
Provider headers are added only on a locally admitted run submission, never initialize,
discovery, read, usage, prompt, resource, or cancellation. There are no cookies, redirects,
proxy-environment handling, credential persistence, provider-network fallback, or retries.
Only JSON object responses with matching typed JSON-RPC IDs and bounded bodies/depth
are accepted; duplicate keys, nonfinite numbers, malformed Unicode and invalid schemas
fail closed. Public allowlist projections remove diagnostics and unknown fields;
known credentials are redacted. Run IDs are bound through nested recovery/receipts.
When a completed hosted run returns private filesystem artifact paths instead of safe
remote references, `adaptorch_get_artifacts` returns `ARTIFACT_REFERENCES_UNAVAILABLE`
with the requested run ID. It does not expose paths, invent links, or suggest resubmission.
Artifact references cannot be local paths, protocol-relative URLs, userinfo-bearing
URLs, query/fragment-bearing URLs (including signed links), traversal paths, or executable
schemes, and are never fetched by this client. These are structural checks plus known-secret
redaction, not proof that an arbitrary URL path contains no unknown capability or token.

Production transport owns a dedicated connection/socket. After connection establishment,
a single cancellable watchdog closes it at the remaining request deadline, including
slow-drip response headers/body. If setup has already exhausted the budget, no POST is
sent. DNS resolution and sequential address connection attempts are OS/stdlib-governed;
the configured timeout is not an unconditional hard wall-clock bound on pre-connection
setup. No unresolved background request worker is created and no write is replayed.

Tenant isolation is service-enforced by authentication. The bridge has no cross-tenant
cache or pooling. If a response provides a tenant ID, subsequent observed tenant IDs
must agree. Without an authenticated identity handshake, this does not independently
prove that the first tenant ID returned by an untrusted server is correct.

## Breaking migration from 0.5.x

- Use `adaptorch-mcp-client`; the ambiguous `adaptorch-mcp` alias is not installed
- Public `full`, local engine, and local HTTP listener modes are rejected
- No private `adaptorch` dependency, private Git source, FastAPI, or uvicorn
- Provider `auto`, keyless, key-command, and fallback settings are rejected explicitly
- Non-loopback plaintext HTTP and the old insecure escape hatch are rejected
- Raw error strings are replaced by fixed, secret-safe recovery guidance
- Metrics/session/resource server-info scope is this client process

Private full/local-engine usage needs a separate private distribution; installing it
is not a workaround for this public package.

## Offline validation

```sh
python -m pytest
ruff check --config pyproject.toml src tests
mypy src
python -m build --no-isolation
```

Tests use neutral synthetic protocol fixtures with blocked sockets, plus explicit
loopback-only slow-drip fixtures. Public projection baseline provenance is recorded in
`evidence/PUBLIC_MODULE_PROVENANCE.json`. A clean wheel install must use only public
wheels, no private Git override, no editable package, and no system-site inheritance.
See `evidence/VALIDATION.md` for actually completed gates and remaining release blockers.

## Current-source compatibility limits

These observations come from the real hosted ASGI implementation exercised with synthetic
in-memory auth/runtime and blocked external sockets. They are not live production results.

| Surface | Candidate behavior | Remaining contract limit |
| --- | --- | --- |
| Nine-tool inventory | Exactly nine validated names | Tool presence does not guarantee every result kind is usable |
| Completed artifact metadata | Safe URI references accepted | Filesystem paths and opaque storage keys produce explicit unavailable error |
| Existing artifact download route | Never called by this client | Server-owned reference contract is separate work; no URLs invented locally |
| Idempotency / resume | Hidden and rejected without admission | Current hosted backend does not support these MCP arguments |
| Quota-exhausted discovery | Fixed bounded429 failure | No REST bypass or invented usage |
| Tenant identity | One authenticated origin/key and observed-ID consistency | First response correctness remains service-enforced |
| Timing | Socket watchdog after connection, no late POST if budget expired | DNS and multi-address connect are not hard wall-clock bounded |
| Provider execution | No production/provider calls performed | Separately authorized hosted first-use remains required |

## License

Copyright ClassicMate. See the canonical [LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
