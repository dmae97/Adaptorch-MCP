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

## Bounded wait exit codes

`adaptorchctl run wait RUN_ID` emits the last observation as JSON. A terminal
`SUCCEEDED` exits 0, `FAILED` exits 8, and `CANCELLED` exits 9. These codes describe
run lifecycle, not result correctness or evidence verification.

A `deadline`, `poll_limit`, `unsupported_status`, or unrecognized stop reason exits
10, even if the last observation looks terminal. Missing or unsupported terminal
observations also exit 10. This means the observation is inconclusive, not that
the server-side run failed. Inspect `reason` and retain the JSON; continue with the
same run ID when appropriate. Waiting never resubmits or cancels a run.

Automation compatibility: `run wait` previously returned 0 for these observations.
Scripts using `set -e` must now handle nonzero exits. `run get` keeps its existing
exit-code behavior; submit and cancel still report command success separately.

## License

Proprietary — Copyright ClassicMate. All rights reserved. See [LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
