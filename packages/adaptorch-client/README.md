# adaptorch-client

`Run` and `EvidenceReport` offer optional typed `verification_diagnostics` and
`verification_diagnostics_schema_version` (`verification.diagnostics/v1`).
`VerificationDiagnostic` carries a closed code, source, scope and optional tool
from `pdftotext`, `pdffonts`, `pdftoppm`, `pdfinfo`. Project reports are untrusted
observations and never override a result. Missing fields support old servers;
malformed or unknown-version optional metadata is removed from both the typed
view and `to_payload()`, preserving every existing run/evidence result field.

Typed, standard-library Python client for the AdaptOrch User API.

## Install

For the current source revision (including request-scoped BYOK), install from this repository:

```bash
pip install "git+https://github.com/dmae97/Adaptorch-MCP.git@main#subdirectory=packages/adaptorch-client"
```

`pip install adaptorch-client` installs the separately published PyPI release;
a repository push does not update that release.

The SDK remains standard-library-only and does not import the private engine.

## First run

Create an `ado_live_*` key at <https://adaptorch.com/app/api-keys>. The raw key is
shown once; keep it in an environment variable and never commit it. This first example
assumes server-managed provider credentials. For a BYOK-only server, use the explicit
credential example below instead.

```python
import os
from uuid import uuid4

from adaptorch_client import AdaptOrchClient, ClientConfig, ProviderCredential

client = AdaptOrchClient(
    ClientConfig(
        api_url="https://adaptorch.com",
        api_key=os.environ["ADAPTORCH_API_KEY"],
    )
)
request_id = str(uuid4())  # retain for this logical submission
run = client.submit_run(
    {
        "subtasks": [{"id": "check", "description": "Reply with the word ready"}],
        "dependencies": [],
    },
    idempotency_key=request_id,
)
print(run.run_id, run.status)
```

`api_url` is the origin only; do not append `/v1`. The client sends tenant keys
as `X-API-Key`, includes a UUID idempotency key on submissions, and exposes
`capabilities()`, `whoami()`, run listing/detail/cancel, evidence, and artifacts.
Provider headers are sent only on that submission, not retained for later reads or cancellation.
FastAPI `detail` errors retain their instructions and stable code while both keys are redacted.
Artifact listings accept both legacy `items` and the hosted `artifacts` map. Map keys
remain available as named `items` for compatibility; raw references are also exposed
in `artifact_urls`, without fetching them or inferring a download URL, size, or hash.
`to_payload()` preserves the wire response.
Cancellation status is backend-specific: local storage currently reports `FAILED` with
`error_class=user_cancelled`, while shared storage may report `CANCELLED`.

## Explicit BYOK and bounded observation

On a BYOK-only server, pass credentials to that submission only. These environment
variables are read by the example, not automatically discovered by the SDK. Use a
concrete provider name: the SDK does not resolve the MCP process setting `auto`.

```python
from uuid import uuid4
from adaptorch_client import PollPolicy, ProviderCredential

request_id = str(uuid4())  # retain for this logical submission
provider_name = os.environ["ADAPTORCH_MCP_PROVIDER"]
if provider_name == "auto":
    raise ValueError("The SDK example requires a concrete provider name")
credential = ProviderCredential(
    provider=provider_name,
    model=os.environ["ADAPTORCH_MCP_PROVIDER_MODEL"],
    api_key=os.environ["ADAPTORCH_MCP_PROVIDER_API_KEY"],
)
run = client.submit_run(
    {"subtasks": [{"id": "check", "description": "Reply with ready"}],
     "synthesis_mode": "auto"},
    idempotency_key=request_id,
    provider_credential=credential,
)
observed = client.wait_for_run(
    run.run_id, policy=PollPolicy(timeout_seconds=30, interval_seconds=1, max_polls=30)
)
print(observed.reason, observed.polls)
```

- `X-Provider`, `X-Provider-Model`, and `X-Provider-Key` are sent only on this POST,
  never in the JSON body or subsequent reads/cancellation. Errors redact both keys.
- Submissions and failed requests are not automatically retried. A timeout can leave
  server execution unresolved; do not create a fresh idempotency key for a blind retry.
  The one transport-level exception is a read (`GET`) on a reused keep-alive
  connection that the server had already closed: it is written once more on a fresh
  connection. Timeouts are never re-sent, and `POST`/`PUT` never use an idle connection.
- Polling uses GET only. It stops at a terminal status, deadline, read-count limit or
  unknown status. It does not cancel server work or impose a provider-spend cap.
  The deadline is checked between HTTP calls; blocking transport interruption remains
  governed by the request's I/O timeout, shortened to the remaining wait budget.
- `SUCCEEDED` describes run liveness, not correctness. Inspect `result_status`,
  `evaluation_status` and `score_validity_status` independently. `synthesis_mode_used`
  is the server-reported admission/collection mode, not proof of final engine execution.
- Legacy missing observations remain `None`. No mode, verification result or build
  identifier is inferred from successful HTTP/run status.
- `get_run`, `cancel_run`, `get_evidence`, and `list_artifacts` reject foreign run IDs.
  Artifact `items` retain IDs/hashes; the current control-plane `artifacts` map is
  exposed separately as `artifact_urls`, without invented IDs or automatic downloads.
- Redirects, ambient proxies, duplicate JSON keys and non-finite JSON numbers are
  rejected/disabled. JSON uses UTF-8 (an optional response BOM is accepted), is
  bounded to 8 MiB and at most 64 container levels. Error messages do not echo
  server-supplied link keys or expose raw recursion failures.

## Connections and performance (0.1.5)

One client keeps up to four idle HTTP/1.1 connections per origin and reuses them for
reads within 4 seconds, so `wait_for_run` pays the TCP and TLS handshake once instead
of on every poll. The TLS context (system trust store, hostname verification, TLS 1.2
minimum) is built once per client, on first HTTPS use. Close the pool when done:

```python
with AdaptOrchClient(ClientConfig(api_url="https://adaptorch.com", api_key=key)) as client:
    observed = client.wait_for_run(run_id)
```

`close()` is safe to call more than once; later calls still work, each on a connection
that is closed afterwards. A client is safe to share between threads.

Response JSON checks (64-level nesting, duplicate keys, finite numbers) run in C-backed
regular expressions and a JSON-only deep copy, roughly halving parse time for large
list pages. The accepted and rejected inputs are unchanged.

## Evidence verdicts

`EvidenceReport` carries `execution_status`, `verification_status` and
`verification_source` when the server reports them. `verification_status` is
`PASSED` only when every verifier check passed; a lone run-level check reports
execution, not verification, and leaves the verdict at `NOT_RUN`. An older server
omits all three (`None`), and an unknown value is preserved as reported. Never treat
`None` or an unknown value as `PASSED`.

```python
report = client.get_evidence(run_id)
if report.verification_status != "PASSED":
    print("not verified:", report.verification_status, report.verification_source)
```

`capabilities()` also exposes the server-reported build, receipt/evidence schema,
MCP toolset and protocol versions. REST version discovery and MCP algorithm discovery
are different contracts. Neither advertises the research-only inference tape as a
hosted replay API.

For the Singapore subscription endpoint and its required server support, see
[ModelStudio Token Plan](../../docs/modelstudio-token-plan.md).

See [algorithm client contract](../../docs/2026-09-08-algorithm-client-contract.md)
and [CLI/API usage](../../docs/adaptorchctl-usage.ko.md) for scope and examples.

## OAuth BYOK (current source)

The existing `api_key` slot can carry an OAuth **access token** for `openai_codex`:

```python
credential = ProviderCredential(
    provider="openai_codex",
    model="gpt-5-codex",  # use a model available to your account
    api_key=os.environ["MY_OAUTH_ACCESS_TOKEN"],
    auth_type="oauth",
    account_id=os.environ["MY_CHATGPT_ACCOUNT_ID"],
)
```

This adds `X-Provider-Auth-Type` and `X-Provider-Account-Id` on submission only.
Both token and account metadata are excluded from repr and error text. The SDK
still performs no environment discovery: the caller obtains/refreshes the access
token using their provider-supported client. Do not send refresh tokens, cookies
or an entire auth JSON file. OAuth does not replace the AdaptOrch tenant key.

Upgrade the control plane with the matching engine support before use. Login UI,
server-side refresh, other providers' OAuth, and credential handoff to RQ workers
are not part of this change. Use an explicit model when shared-store Auto
selection is unavailable. An accepted run still needs terminal result inspection.

## Auto model IDs

On control planes supporting tenant Auto models, use `model="auto"` in the
per-submission `ProviderCredential` (and optionally `"model": "auto"` in the run
body). Keep the actual provider and its key explicit. The server resolves the
model from this tenant's provider default or confirmed history and returns
`model` and `model_selection_source` in the raw result. If there is no candidate,
configure a tenant default or name a model once; the server does not invent an ID.
This does not automatically submit tasks, discover keys, or guarantee provider access.

## Evidence navigation

`navigate_evidence(question, evidence_pack, algorithm_version="graph_v5")` calls
`POST /v1/navigation/evidence` and returns an `EvidenceNavigation`. The server ranks
the passages of a fixed pack; it makes no model call, debits no quota and stores
nothing. `algorithm_version` is one of `NAVIGATION_ALGORITHMS` (`graph_v4`,
`graph_v5`); other values are refused before any request. The result keeps the raw
payload (`to_payload()`) and fails closed unless `evaluation.semantic_support` is
`NOT_EVALUATED`: rankings are not support judgments.

```python
nav = client.navigate_evidence(
    "How is public news reflected in prices?",
    [{"source_id": "market.pdf", "page": 1, "chunk": "a",
      "evidence_text": "Public news is reflected in market prices quickly."}],
)
nav.navigation_version  # "graph_v5"
```

## License

Proprietary — Copyright ClassicMate. All rights reserved. See [LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
