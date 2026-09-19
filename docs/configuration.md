# Configuration

`adaptorch-mcp` delegates to `adaptorch.mcp_server`, so the canonical MCP flags, tools, resources, prompts, safety checks, and transports come from the installed AdaptOrch core release.

## Required Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `ADAPTORCH_CONTROL_PLANE_TOKEN` | yes unless `--api-token` is passed | Upstream AdaptOrch bearer token or cloud API key |
| `ADAPTORCH_CONTROL_PLANE_BASE_URL` | no | Base URL used when `--base-url` is omitted; surrounding whitespace is ignored and non-empty values must be HTTP(S) URLs with a host |
| `ADAPTORCH_MCP_PROVIDER` | BYOK-only deployments | Provider name sent only while submitting a run; requires `ADAPTORCH_MCP_PROVIDER_MODEL`. `auto` picks the one provider whose key variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`) is set in the MCP process environment and fails closed, naming the variables, when none or more than one is |
| `ADAPTORCH_MCP_PROVIDER_MODEL` | BYOK-only deployments | Provider model sent only while submitting a run; requires `ADAPTORCH_MCP_PROVIDER` |
| `ADAPTORCH_MCP_PROVIDER_API_KEY` | Credentialed BYOK providers | Process-local provider key; optional only for keyless CLI providers. Mutually exclusive with `ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND` |
| `ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND` | Rotating BYOK credentials | Local command (no shell) whose stdout is the provider key, resolved per run submission — for expiring credentials such as OAuth access tokens |
| `ADAPTORCH_MCP_PROVIDER_FALLBACK` | Optional | Second provider the control plane tries when the primary fails; requires `ADAPTORCH_MCP_PROVIDER_FALLBACK_MODEL` |
| `ADAPTORCH_MCP_PROVIDER_FALLBACK_MODEL` | With the fallback | Model for the fallback provider |
| `ADAPTORCH_MCP_PROVIDER_FALLBACK_API_KEY` / `_COMMAND` | With the fallback | Fallback credential, static or command-resolved; mutually exclusive |
| `ADAPTORCH_MCP_HTTP_AUTH_TOKEN` | HTTP only | Client-facing bearer token for MCP HTTP/SSE |

Base-url resolution differs by entrypoint:

| Entrypoint | Resolution when `--base-url` is omitted | Default with no env |
| --- | --- | --- |
| `adaptorch-mcp` | `ADAPTORCH_CONTROL_PLANE_BASE_URL` after trimming/validation, then hosted fallback | `https://adaptorch.com` |
| `adaptorch-mcp-smoke` | `ADAPTORCH_CONTROL_PLANE_BASE_URL`, then local smoke target | `http://127.0.0.1:8000` |
| `create_default_mcp_http_app()` | Delegates to the AdaptOrch engine and reads environment only | engine default |

Pass `--base-url` explicitly in checked-in MCP client configs for reproducible behavior. Do not embed credentials in base URLs; use token environment variables instead.

The connector sends `ado_*` tenant keys as `X-API-Key`; other control-plane tokens use `Authorization: Bearer <token>`. Provider credentials are separate from tenant authentication.

For the Singapore subscription endpoint, see [ModelStudio Token Plan](modelstudio-token-plan.md).
It requires a control-plane engine with the `modelstudio-maas` provider; a client upgrade
alone does not upgrade the server.

## BYOK provider credentials

A BYOK-only control plane returns `401 byok_credentials_required` unless run submission includes provider credentials. Configure them in the MCP process environment rather than in a tool argument:

```bash
export ADAPTORCH_MCP_PROVIDER="openai"
export ADAPTORCH_MCP_PROVIDER_MODEL="gpt-4.1-mini"
export ADAPTORCH_MCP_PROVIDER_API_KEY="<provider-api-key>"
```

If the provider's own key variable is already in the environment, `auto` reads it
instead of a copy. The model is still yours to name; `ADAPTORCH_MCP_PROVIDER_API_KEY`
is refused alongside `auto` because the wrapper could not tell which provider it
belongs to:

```bash
export OPENAI_API_KEY="<provider-api-key>"      # exactly one provider key present
export ADAPTORCH_MCP_PROVIDER="auto"
export ADAPTORCH_MCP_PROVIDER_MODEL="gpt-4.1-mini"
```

The wrapper fails closed when provider/model are incomplete, when `auto` finds no
provider key or more than one (the message names the variables, never a value), or when the installed engine is too old for provider-credential forwarding. The key is excluded from repr output, MCP schemas, JSON request bodies, status/artifact/usage requests, and error text. It is attached only to `POST /v1/runs` as `X-Provider-Key`; provider and model use `X-Provider` and `X-Provider-Model`. The control plane uses the credential for that request and does not store it, while the local MCP process retains its environment until shutdown.

`ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND` covers credentials that rotate faster
than a process lifetime — OAuth access tokens read from a local credential
store. The command is tokenized with `shlex.split`, executed without a shell,
and must print exactly the key on stdout; stderr and exit details never reach
tool responses. It is re-resolved on every run submission, so a token that
expires mid-session is picked up fresh instead of failing until restart.
Mutually exclusive with `ADAPTORCH_MCP_PROVIDER_API_KEY` and refused with
`ADAPTORCH_MCP_PROVIDER=auto`.

```bash
# Claude subscription via an OAuth credential store (the reader prints the
# current access token from ~/.omk/agent/auth.json; OMK owns refresh).
export ADAPTORCH_MCP_PROVIDER="anthropic"
export ADAPTORCH_MCP_PROVIDER_MODEL="claude-opus-5"
export ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND="$HOME/.config/omk/adaptorch_token.py anthropic"
```

OAuth access tokens (`sk-ant-oat*`) are sent to Anthropic as
`Authorization: Bearer` with `anthropic-beta: oauth-2025-04-20` by the
control-plane engine; a static `x-api-key` credential keeps the `x-api-key`
header. Google OAuth tokens (`ya29.*`) likewise go through `Bearer` instead of
the `?key=` API-key parameter. That Bearer mapping ships with the
control-plane release — an older deployment cannot accept OAuth tokens no
matter how they are supplied.

The command can resolve any subscription account in the store — the engine
provider name and auth form are what differ:

| auth.json account | `ADAPTORCH_MCP_PROVIDER` | Credential form sent |
| --- | --- | --- |
| `anthropic` | `anthropic` | `sk-ant-oat*` → Bearer + Claude Code identity (verified) |
| `xai` | `xai` | OAuth access token → Bearer on the OpenAI-compatible surface (verified) |
| Google OAuth account | `google` | `ya29.*` → Bearer |
| `openai-codex` | none | Codex speaks a bespoke SSE Responses protocol at `chatgpt.com/backend-api/codex/responses` with a `chatgpt-account-id` header — not the OpenAI chat-completions contract, so it needs its own provider rather than a credential mapping |
| `cursor` | none | Connect-framed protobuf over HTTP/2 at `api2.cursor.sh` — not an HTTP+JSON LLM API |
| `meta`, `devin`, `opencode-go` | none | OAuth for a product surface, not an engine-supported LLM API |
| `deepseek`, `zai`, `kimi-coding`, `xiaomi`, `crofai`, `commandcode`, `freellmpool` | none | OpenAI-compatible vendor keys whose base URLs the control plane does not expose over BYOK |

An account that does not map to an engine provider fails closed — the run
never reaches the control plane with a credential the server cannot use.

### Fallback provider

A subscription credential can be rate-limited while remaining perfectly valid.
The optional fallback triple names a second provider that the control plane
tries when the primary call fails, so a 429 degrades to a slower answer
instead of a failed run:

```bash
export ADAPTORCH_MCP_PROVIDER="anthropic"
export ADAPTORCH_MCP_PROVIDER_MODEL="claude-opus-5"
export ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND="$HOME/.config/omk/adaptorch_token.py anthropic"

export ADAPTORCH_MCP_PROVIDER_FALLBACK="xai"
export ADAPTORCH_MCP_PROVIDER_FALLBACK_MODEL="grok-4.6"
export ADAPTORCH_MCP_PROVIDER_FALLBACK_API_KEY_COMMAND="$HOME/.config/omk/adaptorch_token.py xai"
```

The fallback carries its own key because a hosted BYOK run has no provider key
in the server environment to fall back on; it rides the `X-Provider-Fallback`,
`X-Provider-Fallback-Model` and `X-Provider-Fallback-Key` headers under the
same rules as the primary (never stored, never echoed, redacted in errors).
A half-specified fallback is refused rather than dropped: one that looked
configured and never fired would only be discovered during an outage.

The chain is tried in order on any provider error the engine classifies as
such — including `429` after the primary's own retries are exhausted. When
every entry fails the run is marked `DEGRADED` with the per-provider reasons,
keys redacted.

For source parity against an unreleased engine checkout, run `make engine-local ENGINE_PATH=../adaptorch` before `make check`.

## HTTP Environment

| Variable | Purpose |
| --- | --- |
| `ADAPTORCH_MCP_ALLOWED_ORIGINS` | Comma-separated allowed origins for HTTP/SSE clients. |
| `ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES` | Maximum accepted HTTP request body size. |
| `ADAPTORCH_MCP_REQUEST_TIMEOUT_SECONDS` | HTTP request timeout budget. |
| `ADAPTORCH_MCP_MAX_SSE_SUBSCRIBERS` | Maximum concurrent SSE subscribers. |
| `ADAPTORCH_MCP_TIMEOUT_SECONDS` | Control-plane client timeout for embedded/app-factory usage. |
| `ADAPTORCH_MCP_HTTP_HOST` / `ADAPTORCH_MCP_HTTP_PORT` | Shell/template values for `--http-host` and `--http-port`; CLI flags are authoritative. |

## Engine-delegated optional algorithm controls (latest)

`adaptorch-mcp` forwards these controls to the installed `adaptorch` engine. The
wrapper does not implement routing, synthesis, quality scoring, or benchmark
algorithms itself.

### Environment controls

| Variable | Scope | Notes |
| --- | --- | --- |
| `ADAPTORCH_REPRODUCIBLE` | Benchmark/eval beta | Fixes benchmark clock/RNG sources and canonicalizes record timing/path fields. It does not cover live-provider outputs, parallel-suite record order, cassettes, traces, or report timing aggregates. |
| `ADAPTORCH_ROUTER_ACCURACY_GATE` | Online router | `point` is the default; `wilson` compares learned-router adoption against a Wilson lower bound. Advanced/operator use. |
| `ADAPTORCH_PAPER_SEMANTIC_WEIGHT` | Synthesis | Default is `0.35`. Nonzero semantic weight, plus CJK/Hangul inputs, use Python scoring rather than the native fast path. |

### Engine API/config controls

| Control | Scope | Notes |
| --- | --- | --- |
| `manifest_canonical_sha256` | Benchmark manifest | Importable as `adaptorch.benchmarking.manifest_canonical_sha256`; hashes canonical nonvolatile manifest fields. |
| `pass_rate_credit` | Quality signal | Opt-in partial credit in `adaptorch.quality_signal.compute_quality`; do not claim it changes `AdaptOrchEngine` router feedback by default. |
| `quality_signal` | Online-router learning | Exact-answer tokens are compared before fuzzy gold-label matching. |
| `prefer_multi_model_ensemble_singleton` | Routing threshold | Tri-state: unset auto-enables when at least two ensemble providers exist and synthesis mode is not `direct`, unless an explicit debate-singleton preference wins; explicit `false` disables the auto preference. |
| `prefer_ensemble_singleton` | MCP run hint | Tri-state hint (`true`/`false`/`null`) forwarded by MCP/benchmark run options; `false` is an explicit opt-out, `null`/omitted leaves the auto policy in charge. |
| Online-router knobs | Operator tuning | `retrain_window`, `min_loo_accuracy`, `min_posterior`, `quality_floor`, `use_quality_weights`, `use_failure_evidence`, `exploration_rate`, `max_observations`, `cv`, and `kfold_k`. |

## Common Flags

```bash
adaptorch-mcp --help
```

Important flags:

- `--transport stdio|http`
- `--base-url <url>`
- `--api-token <token>`
- `--timeout-seconds <float>`
- `--stdio-framing newline|content-length`
- `--http-host <host>`
- `--http-port <port>`
- `--http-auth-token <token>`

## Local stdio

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp --transport stdio --base-url http://127.0.0.1:8000
```

## Production stdio

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<tenant-api-key>"
adaptorch-mcp --transport stdio --base-url https://adaptorch.com
```

## Local HTTP

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<upstream-token>"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<mcp-client-token>"
adaptorch-mcp \
  --transport http \
  --base-url https://adaptorch.com \
  --http-host 127.0.0.1 \
  --http-port 8765 \
  --http-auth-token "$ADAPTORCH_MCP_HTTP_AUTH_TOKEN"
```

Clients must call `/mcp` or `/mcp/sse` with:

```text
Authorization: Bearer <mcp-client-token>
```

## Diagnostics

```bash
adaptorch-mcp-doctor
adaptorch-mcp-doctor --json
adaptorch-mcp-doctor --strict
```

`adaptorch-mcp-doctor` is safe to paste into support tickets: token values are redacted and only set/length metadata is shown. JSON output includes a `controlPlane` block with the default URL, redacted environment URL, resolved URL, source (`env` or `hosted-default`), and invalid-env status.

## stdio Smoke Test

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.com
```

The command starts `adaptorch-mcp --transport stdio`, sends `initialize` and `tools/list`, then verifies the expected core tool subset. When neither `--base-url` nor `ADAPTORCH_CONTROL_PLANE_BASE_URL` is set, smoke intentionally targets `http://127.0.0.1:8000` for local development. Add repeatable `--expected-tool <name>` flags when validating a specific hosted/core release.

## Public Plan Catalog

AdaptOrch MCP exposes the hosted cloud plan catalog via:

- Tool: `adaptorch_plan_catalog`
- Resource: `adaptorch://plans/cloud`
- Capability field: `cloud_plan_catalog`

Current catalog: Starter `$0`, Pro `$39`, Team `$149`.
