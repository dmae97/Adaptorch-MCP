# adaptorch-cli

Run/evidence JSON may include the SDK's safe, versioned `verification_diagnostics`.
Project reports remain untrusted observations. Invalid optional metadata is
omitted by the SDK, including in CLI JSON; it does not turn a valid run response
into a CLI error. Existing failed/cancelled/inconclusive exits stay 8/9/10,
and a stopped wait still exits 10. PDF tools are not global CLI prerequisites.

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

## Evidence navigation

```bash
adaptorchctl navigate --question "How is public news reflected in prices?" \
  --evidence-pack pack.json [--algorithm graph_v5|graph_v4]
```

`pack.json` is a JSON array of `{source_id, page, chunk, evidence_text}` objects, or
an object with an `evidence_pack` field (`-` reads stdin). The command is read-only:
no model call, no quota, nothing stored.

```bash
adaptorchctl run report RUN_ID --out report.json
adaptorchctl run report RUN_ID --format pdf --locale ko --out report.pdf
```

Downloads a saved terminal run's report, including the saved LLM answer, to a new
file and prints `{run_id, format, locale, media_type, bytes, sha256, snapshot_sha256,
path}`. It never submits or replays a run and never overwrites an existing file
(exit 2). `--locale` is PDF only. A run that is not terminal exits 5 (HTTP 409); an
unrenderable PDF exits 7 (HTTP 503) and the JSON report remains available.

## Bounded wait exit codes

`adaptorchctl run wait RUN_ID` emits the last observation as JSON. A terminal
`SUCCEEDED` exits 0, `FAILED` exits 8, and `CANCELLED` exits 9. These codes describe
run lifecycle, not result correctness or evidence verification.

`--timeout` (default 120 s) and `--interval` (default 1 s) set the wait. Since 0.1.5
the read budget defaults to `ceil(timeout / interval) + 1`, so the deadline, not a
fixed 100-read cap, ends a long wait; `--max-polls N` sets an explicit cap. Reads
reuse one keep-alive connection.

A `deadline`, `poll_limit`, `unsupported_status`, or unrecognized stop reason exits
10, even if the last observation looks terminal. Missing or unsupported terminal
observations also exit 10. This means the observation is inconclusive, not that
the server-side run failed. Inspect `reason` and retain the JSON; continue with the
same run ID when appropriate. Waiting never resubmits or cancels a run.

Output piped into a reader that exits early (`adaptorchctl run list | head -c 100`)
no longer ends in a `BrokenPipeError` traceback; the exit code still reports the
command. A failure with no HTTP response (DNS, connect, TLS or timeout) prints
`request failed (no HTTP response: network, TLS or timeout)` and exits 7.

Automation compatibility: `run wait` previously returned 0 for these observations.
Scripts using `set -e` must now handle nonzero exits. `run get` keeps its existing
exit-code behavior; submit and cancel still report command success separately.

## License

Proprietary — Copyright ClassicMate. All rights reserved. See [LICENSE](https://github.com/dmae97/Adaptorch-MCP/blob/main/LICENSE).
