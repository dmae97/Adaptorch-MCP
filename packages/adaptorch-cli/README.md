# adaptorch-cli

Independent AdaptOrch SaaS CLI. Installs the `adaptorchctl` command and uses `adaptorch-client`; it does not invoke `adaptorch` or `adaptorch-mcp`.

Log in once and every command picks the credential up:

```bash
adaptorchctl auth login      # prompts for the key, verifies it, stores it at
                             # ~/.config/adaptorch/config.json (mode 0600)
adaptorchctl auth status     # shows credential_source: env | config | none
adaptorchctl auth logout     # removes the stored key
```

`ADAPTORCH_API_KEY` still works and always wins over the stored key, so CI
keeps injecting secrets via the environment. `config set provider.{name,model,
api_key}` persists BYOK wiring for `run submit`; the env vars
`ADAPTORCH_PROVIDER`, `ADAPTORCH_PROVIDER_MODEL`, and
`ADAPTORCH_PROVIDER_API_KEY` override the stored values. Provider credentials
become `X-Provider`, `X-Provider-Model`, and `X-Provider-Key` only on
`run submit`; reads and cancellation never receive the provider key.
`ADAPTORCH_API_KEY` remains the separate tenant key.

Install the current `adaptorch-client` and `adaptorch-cli` source packages together.
A git push does not replace a previously published PyPI version.

See [`../../docs/adaptorchctl-usage.ko.md`](../../docs/adaptorchctl-usage.ko.md) for usage.

## License

Proprietary — Copyright ClassicMate. All rights reserved. See [LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
