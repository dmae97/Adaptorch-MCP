# AdaptOrch GitHub Action

The action submits a task to the AdaptOrch User API, waits for a terminal run,
and exposes execution and evidence status as separate outputs. It uses the public
Python client checked out with the action's Git ref; it does not install or include
the private engine. Python 3.11 or newer and Bash must be available on the runner.
The example below targets GitHub-hosted Ubuntu runners.

The following example is usable after this action is merged into `main`. For a
production workflow, replace `main` with the full commit SHA of a reviewed release.
The action is not published to GitHub Marketplace merely by merging it.

## Minimal workflow

Create `ADAPTORCH_API_KEY` and `MODEL_PROVIDER_API_KEY` in the repository's
**Settings → Secrets and variables → Actions**. Create an AdaptOrch API key at
[adaptorch.com/app/api-keys](https://adaptorch.com/app/api-keys). Hosted model-backed
runs require a provider, model and provider key (BYOK).

```yaml
name: AdaptOrch run
on: workflow_dispatch

permissions:
  contents: read

jobs:
  adaptorch:
    runs-on: ubuntu-latest
    steps:
      - id: adaptorch
        uses: dmae97/Adaptorch-MCP@main
        with:
          api-key: ${{ secrets.ADAPTORCH_API_KEY }}
          provider: openai
          provider-model: gpt-4.1-mini
          provider-api-key: ${{ secrets.MODEL_PROVIDER_API_KEY }}
          prompt: Give a concise checklist for reviewing a Python release.
          verification: report
      - name: Inspect execution and verification
        shell: bash
        env:
          RUN_ID: ${{ steps.adaptorch.outputs.run-id }}
          STATUS: ${{ steps.adaptorch.outputs.status }}
          VERIFICATION: ${{ steps.adaptorch.outputs.verification-status }}
        run: |
          printf 'Run: %s\nExecution: %s\nVerification: %s\n' "$RUN_ID" "$STATUS" "$VERIFICATION"
```

Each submission consumes an AdaptOrch run if admitted, and provider charges can
apply. The generated submission UUID is printed before the request and exposed as
`idempotency-key` so that an uncertain response can be recovered without blindly
creating a second run.

## Supply CI context or a run specification

Pass a workspace-relative UTF-8 file with `context-file` alongside `prompt`, or
use `run-spec-file` instead of `prompt` for the v1 JSON run specification. Only the
explicitly provided prompt, context or JSON is sent; the action does not check out
the repository, collect diffs, or send files automatically. Both file types have a
1 MiB limit; the prompt has a 64 KiB limit. Paths must stay inside the workspace.

For example, after a workflow checks out its own repository and creates a curated
`validation-summary.txt`, the action step can use:

```yaml
      - id: adaptorch
        uses: dmae97/Adaptorch-MCP@main
        with:
          api-key: ${{ secrets.ADAPTORCH_API_KEY }}
          provider: openai
          provider-model: gpt-4.1-mini
          provider-api-key: ${{ secrets.MODEL_PROVIDER_API_KEY }}
          prompt: Summarize the supplied validation results and identify unknowns.
          context-file: validation-summary.txt
          report-file: adaptorch-report.json
```

`report-file` is opt-in and must name a new file in an existing workspace directory.
It contains the saved run's input and output. The action does not upload it as a
workflow artifact or print its contents. Download requires a terminal run and a
server that supports the run report endpoint.

## Inputs

| Input | Meaning |
| --- | --- |
| `api-key` | Required AdaptOrch API key. |
| `provider`, `provider-model`, `provider-api-key` | Supply all three for BYOK, or omit all three only if the server supports managed credentials. |
| `prompt` | A task description. Choose exactly one of this, `run-spec-file`, or `resume-run-id`. |
| `run-spec-file` | Workspace-relative JSON task specification with 1–50 `subtasks`. |
| `context-file` | Workspace-relative UTF-8 context, only with `prompt`. |
| `resume-run-id` | Observe an existing run without a new submission. Do not also pass a prompt, run spec, context, idempotency key, or provider credentials. |
| `idempotency-key` | Optional hyphenated UUID. If omitted, a UUID is generated for this submission. |
| `api-url` | API origin, default `https://adaptorch.com`. HTTPS is required except for exact loopback HTTP hosts. |
| `wait-timeout-seconds` | Polling deadline, 1–3600; default 180. |
| `poll-interval-seconds` | Polling interval, 1–60; default 2. |
| `verification` | `off`, `report` (default), or `required`. |
| `report-file` | Optional new workspace-relative path for the saved JSON run report. |

## Outputs and failure behavior

`run-id`, `status`, `result-status`, `evaluation-status`, `verification-status`,
`idempotency-key`, and, when a report is saved, `report-sha256` are available as
step outputs. Missing or unrecognized optional statuses are reported as
`NOT_REPORTED` or `UNKNOWN`; failed evidence reads are `UNAVAILABLE`.

An unsuccessful run, an unknown status, a polling deadline, invalid input or a
request failure fails the action. `verification: report` reports the available
verdict but does not fail solely because it is missing or failed. Use
`verification: required` to fail unless the server explicitly reports `PASSED`.
`SUCCEEDED` means execution finished; it does not imply answer correctness or a
passed verification. `result-status` can independently be `DEGRADED`.

A timeout or lost response does not prove that no run was created. The action
never automatically retries a submission and does not cancel server work on a
polling deadline. To retry an uncertain submission, use the **same**
`idempotency-key` with the unchanged request. A fresh workflow attempt generates a
new key unless one is supplied. If the run ID is already known, use
`resume-run-id` instead; it only reads. Configure workflow recovery around these
outputs and the submission UUID in the log.

## Security

Only run secret-bearing workflows in a trusted context. GitHub does not normally
provide repository secrets to workflows triggered by forked pull requests. Avoid
`pull_request_target` combined with checkout or execution of untrusted PR code.
Inputs are sent to the configured AdaptOrch service and may be sent to the chosen
model provider, so curate context and inspect report files before sharing them.
The chosen `api-url` receives the AdaptOrch key and, on submission, provider
credentials; use only a trusted service origin. Pin the action to a reviewed full
commit SHA when using it in production.

The action does not post pull request comments, change repository files, or grant
release approval. Its evidence status reflects what the server reports and is not
an independent correctness proof.
