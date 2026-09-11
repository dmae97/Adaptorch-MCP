# adaptorch-client

Typed, standard-library Python client for the AdaptOrch User API.

## Install

For the current source revision (including request-scoped BYOK), install from this repository:

```bash
pip install "git+https://github.com/dmae97/Adaptorch-MCP.git@main#subdirectory=packages/adaptorch-client"
```

`pip install adaptorch-client` installs the separately published PyPI release;
a repository push does not update that release.

## First run

Create an `ado_live_*` key at <https://adaptorch.com/app/api-keys>. The raw key is
shown once; keep it in an environment variable and never commit it.

```python
import os

from adaptorch_client import AdaptOrchClient, ClientConfig, ProviderCredential

client = AdaptOrchClient(
    ClientConfig(
        api_url="https://adaptorch.com",
        api_key=os.environ["ADAPTORCH_API_KEY"],
    )
)
run = client.submit_run(
    {
        "subtasks": [{"id": "check", "description": "Reply with the word ready"}],
        "dependencies": [],
    },
    idempotency_key="11111111-1111-4111-8111-111111111111",
    provider_credential=ProviderCredential(
        provider="openai",
        model="gpt-4o-mini",
        api_key=os.environ["OPENAI_API_KEY"],
    ),
)
print(run.run_id, run.status)
```

`api_url` is the origin only; do not append `/v1`. The client sends tenant keys
as `X-API-Key`, includes a UUID idempotency key on submissions, and exposes
`capabilities()`, `whoami()`, run listing/detail/cancel, evidence, and artifacts.
Provider headers are sent only on that submission, not retained for later reads or cancellation.
FastAPI `detail` errors retain their instructions and stable code while both keys are redacted.
Artifact listings accept both legacy `items` and the hosted `artifacts` map. Map entries
have names but no inferred download URL, file size, or hash; `to_payload()` preserves the wire response.
Cancellation status is backend-specific: local storage currently reports `FAILED` with
`error_class=user_cancelled`, while shared storage may report `CANCELLED`.

See [`../../docs/adaptorchctl-usage.ko.md`](../../docs/adaptorchctl-usage.ko.md) for the current CLI and API usage guide.

## Auto model IDs

On control planes supporting tenant Auto models, use `model="auto"` in the
per-submission `ProviderCredential` (and optionally `"model": "auto"` in the run
body). Keep the actual provider and its key explicit. The server resolves the
model from this tenant's provider default or confirmed history and returns
`model` and `model_selection_source` in the raw result. If there is no candidate,
configure a tenant default or name a model once; the server does not invent an ID.
This does not automatically submit tasks, discover keys, or guarantee provider access.

## License

Proprietary — Copyright ClassicMate. All rights reserved. See [LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
