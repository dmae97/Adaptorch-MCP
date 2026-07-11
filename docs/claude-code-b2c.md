# B2C Claude Code Experience Notes

This package should feel useful to individual Claude Code users before they learn the broader AdaptOrch platform. Optimize the first-run path around a small, predictable tool surface.

## Get your API key (first thing)

1. Sign up at [adaptorch.com/app/signup](https://adaptorch.com/app/signup)
2. Open [adaptorch.com/app/api-keys](https://adaptorch.com/app/api-keys) and generate a key (starts with `ado_`)
3. Starter `$0` includes API key access, 1,000 calls/month, and shadow mode

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="ado_..."
```

### First-run story

Signup → `/app/api-keys` → copy `ado_*` once → set `ADAPTORCH_CONTROL_PLANE_TOKEN` in the Claude Code MCP env → call `adaptorch_run` or `adaptorch_list_runs` → open `/app/runs` to see the same tenant run list on the dashboard.

한국어: 가입 후 `/app/api-keys`에서 `ado_*`를 만들고 MCP 환경 변수에 넣으면 Claude Code 실행/목록 결과가 대시보드 `/app/runs`에 이어집니다.

## Recommended default tool surface

Expose all server tools, but document these five first:

| Priority | Tool | Why it is felt quickly |
| --- | --- | --- |
| 1 | `adaptorch_route_topology` | Instant local routing feedback. Users see why a task should be singleton, pipeline, DAG, or ensemble before spending tokens. |
| 2 | `adaptorch_run` | Turns a vague coding goal into an AdaptOrch-controlled run with synthesis/telemetry instead of a single brittle pass. |
| 3 | `adaptorch_get_run` | Lets Claude Code poll status without asking the user to inspect dashboards. |
| 4 | `adaptorch_get_artifacts` | Makes evidence and outputs retrievable inside the coding conversation. |
| 5 | `adaptorch_plan_catalog` | Confirms the install is current and gives users a simple hosted/free-tier mental model. |

Auto-approve only outputs that are safe for the client context. For trusted local clients, these local/read metadata tools are the safest defaults:

```text
adaptorch_route_topology
adaptorch_server_metrics
adaptorch_capabilities
adaptorch_plan_catalog
```

Keep these manually approved in shared or production clients unless run payloads, artifacts, and traces are already sanitized:

```text
adaptorch_run
adaptorch_cancel_run
adaptorch_get_run
adaptorch_get_artifacts
adaptorch_list_runs
adaptorch_get_traces
```

## Fastest perceived wins

1. **Less planning uncertainty** — `adaptorch_route_topology` gives a concrete routing decision immediately without external calls.
2. **Fewer failed long tasks** — `adaptorch_run` applies AdaptOrch's router/synthesis/verification path for tasks that would otherwise exceed one Claude Code pass.
3. **Evidence in the chat** — `adaptorch_get_artifacts` makes results and proof easier to surface without context switching.
4. **Safer supportability** — `adaptorch-mcp-doctor` and `adaptorch-mcp-smoke` turn install failures into copy-pasteable, redacted diagnostics.
5. **Lower setup friction** — after PyPI publishing, `uvx adaptorch-mcp --help` gives an immediate no-clone install path.

## B2C install copy

```bash
uvx adaptorch-mcp --help
```

For actual MCP use:

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
uvx adaptorch-mcp --transport stdio --base-url https://adaptorch.com
```

For verification:

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
uvx --with "adaptorch[api]" adaptorch-mcp-smoke --base-url https://adaptorch.com
```

## Product message

> Add AdaptOrch to Claude Code when a task is too large, too ambiguous, or too expensive to run as a single pass. Route first, run with evidence, then pull artifacts back into the chat.

## Known limitation

The wrapper is only as current as the installed `adaptorch` dependency. For B2C installs, publish `adaptorch` core first or users must install it from GitHub.
