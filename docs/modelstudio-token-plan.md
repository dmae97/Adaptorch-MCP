# ModelStudio Token Plan through MCP and SDK

This source integration requires an AdaptOrch control plane containing the new
`modelstudio-maas` provider. Updating the client alone does not update the server.
It is not a package release, deployment, or permission for automated benchmarks.
The current pinned core does not expose this provider; the conditional integration
test is skipped. The examples apply only after a supporting engine is installed.

## Endpoint identity

`modelstudio-maas` is the Singapore **Token Plan** endpoint:

```text
https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions
```

It is not the separate Coding Plan endpoint or general ModelStudio pay-as-you-go.
The engine pins the URL, blocks redirects, ignores ambient proxies for this host,
makes one transport attempt, and rejects provider fallback. These bounds do not
limit the engine's total reroutes or additional model calls.

No model alias is rewritten. `deepseek-v4-flash-0731` stays that requested ID; a
successful request does not establish that the deployment is V4.1 Flash.

## MCP

Configure the MCP process, not the tool's JSON arguments:

```bash
export ADAPTORCH_MCP_PROVIDER=modelstudio-maas
export ADAPTORCH_MCP_PROVIDER_MODEL=deepseek-v4-flash-0731
export ADAPTORCH_MCP_PROVIDER_API_KEY="<token-plan-key>"
```

Keep the tenant token and the control-plane URL configured separately. The key
travels only on `POST /v1/runs` via `X-Provider-Key`; provider and model travel in
`X-Provider` and `X-Provider-Model`. Status and artifact reads carry no provider key.

A supporting engine may export `MODELSTUDIO_TOKEN_PLAN_API_KEY` in its provider
map; only then can it participate in `ADAPTORCH_MCP_PROVIDER=auto` discovery.
It does not participate with the current engine pin. Exactly one exported
provider key must be present. Prefer an explicit provider when several
keys exist. The wrapper does not automatically read an OMK key file.

## SDK

The standard-library SDK uses its existing BYOK interface. `ADAPTORCH_API_URL`
must point to a control plane containing this provider, not to the Token Plan URL.
The example uses the current control plane's nested `payload` run envelope.

```python
import os
from uuid import uuid4

from adaptorch_client import AdaptOrchClient, ClientConfig, ProviderCredential

client = AdaptOrchClient(ClientConfig(
    api_url=os.environ["ADAPTORCH_API_URL"],
    api_key=os.environ["ADAPTORCH_API_KEY"],
))
credential = ProviderCredential(
    provider="modelstudio-maas",
    model="deepseek-v4-flash-0731",
    api_key=os.environ["MODELSTUDIO_TOKEN_PLAN_API_KEY"],
)
run = client.submit_run(
    {"payload": {"subtasks": [{"id": "v1", "description": "Reply with READY"}]},
     "synthesis_mode": "paper"},
    idempotency_key=str(uuid4()),
    provider_credential=credential,
)
print(run.run_id, run.status)
```

Retain the idempotency key for the logical submission; do not re-submit a timed-out
run under a new ID. The SDK does not import or reimplement the private algorithm.

## Supported scope

- Standard non-streaming Chat Completions via the engine's existing transport.
- Existing temperature, output cap, timeout, and usage accounting.
- Requested model IDs and synthesis-mode observations remain unmodified.
- No new sampling controls, max-effort benchmark parity, or candidate replay tool.
- The local in-process MCP backend still refuses request-scoped BYOK ensembles;
  configure its existing execution-provider environment for a local single-user run,
  or use the authenticated control-plane backend for request-scoped BYOK.
- The [Token Plan usage rules](https://www.alibabacloud.com/help/zh/model-studio/token-plan-personal-overview)
  still govern interactive use and prohibit automated scripts/non-interactive batches.

`packages/adaptorch-mcp/tests/test_modelstudio_plan_flow.py` exercises SDK and
hardened MCP requests through the real local control-plane engine with only the
provider HTTP response simulated. It is connection-contract evidence, not a live
provider benchmark.
