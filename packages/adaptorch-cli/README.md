# adaptorch-cli

Independent AdaptOrch SaaS CLI. Installs the `adaptorchctl` command and uses `adaptorch-client`; it does not invoke `adaptorch` or `adaptorch-mcp`.

For BYOK run submissions, set `ADAPTORCH_PROVIDER`, `ADAPTORCH_PROVIDER_MODEL`,
and `ADAPTORCH_PROVIDER_API_KEY` together. They become `X-Provider`,
`X-Provider-Model`, and `X-Provider-Key` only on `run submit`; reads and cancellation
never receive the provider key. `ADAPTORCH_API_KEY` remains the separate tenant key.

Install the current `adaptorch-client` and `adaptorch-cli` source packages together.
A git push does not replace a previously published PyPI version.

See [`../../docs/adaptorchctl-usage.ko.md`](../../docs/adaptorchctl-usage.ko.md) for usage.
