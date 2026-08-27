# adaptorch-client

Typed, standard-library Python client for the AdaptOrch User API.

## Install

The package is currently distributed from this repository rather than PyPI. Install
it from the package subdirectory:

```bash
pip install "adaptorch-client @ git+https://github.com/dmae97/Adaptorch-MCP.git#subdirectory=packages/adaptorch-client"
```

## First run

Create an `ado_live_*` key at <https://adaptorch.com/app/api-keys>. The raw key is
shown once; keep it in an environment variable and never commit it.

```python
import os

from adaptorch_client import AdaptOrchClient, ClientConfig

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
)
print(run.run_id, run.status)
```

`api_url` is the origin only; do not append `/v1`. The client sends tenant keys
as `X-API-Key`, includes a UUID idempotency key on submissions, and exposes
`capabilities()`, `whoami()`, run listing/detail/cancel, evidence, and artifacts.

See [`../../docs/adaptorchctl-usage.ko.md`](../../docs/adaptorchctl-usage.ko.md) for the current CLI and API usage guide.

## License

Proprietary — Copyright ClassicMate. All rights reserved. See [LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
