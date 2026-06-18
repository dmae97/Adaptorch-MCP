# AdaptOrch MCP

<p align="center">
  <a href="https://adaptorch.ai.kr"><img src="assets/readme-hero.png" alt="AdaptOrch MCP — route, run, and retrieve evidence from Claude Code" width="100%"></a>
</p>

<p align="center">
  <a href="https://adaptorch.ai.kr"><strong>adaptorch.ai.kr</strong></a>
  ·
  <a href="docs/configuration.md">Configuration</a>
  ·
  <a href="docs/tools.md">Tools</a>
  ·
  <a href="docs/claude-code-b2c.md">Claude Code guide</a>
  ·
  <a href="docs/publishing.md">Publishing</a>
  ·
  <a href="https://arxiv.org/abs/2602.16873">Paper</a>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio%20%7C%20HTTP-22d3ee?style=flat-square">
  <img alt="License Apache 2.0" src="https://img.shields.io/badge/license-Apache--2.0-a78bfa?style=flat-square">
  <img alt="Public ready" src="https://img.shields.io/badge/public--ready-yes-86efac?style=flat-square">
  <a href="https://arxiv.org/abs/2602.16873"><img alt="arXiv 2602.16873" src="https://img.shields.io/badge/arXiv-2602.16873-b31b1b?style=flat-square&logo=arxiv&logoColor=white"></a>
</p>

**AdaptOrch MCP** is the public MCP wrapper for [AdaptOrch](https://adaptorch.ai.kr): a reliability kernel that lets Claude Code route tasks, launch orchestrated runs, and pull evidence artifacts back into the chat.

Use it when a coding task is too large, too ambiguous, or too expensive to trust to one single-pass response.

```text
Claude Code → AdaptOrch MCP → route topology → run with synthesis → retrieve artifacts
```

## Research paper

AdaptOrch MCP follows the AdaptOrch research line. Read the paper on arXiv:

- Abstract page: [arxiv.org/abs/2602.16873](https://arxiv.org/abs/2602.16873)
- HTML paper: [arxiv.org/html/2602.16873v1](https://arxiv.org/html/2602.16873v1)

<p align="center">
  <a href="https://arxiv.org/html/2602.16873v1">
    <img src="https://arxiv.org/html/2602.16873v1/x1.png" alt="Figure from the AdaptOrch arXiv HTML paper" width="88%">
  </a>
</p>

<p align="center"><sub>Figure preview is sourced from the arXiv HTML version.</sub></p>

## Install

### pip

```bash
pip install adaptorch-mcp
```

If AdaptOrch core is not yet on PyPI, install it from GitHub first:

```bash
pip install "adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git"
pip install adaptorch-mcp
```

### uvx (one-shot, no install)

```bash
uvx adaptorch-mcp --help
```

With the adaptorch dependency from GitHub:

```bash
uvx --with "adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git" adaptorch-mcp --help
```

## Why Claude Code users feel it quickly

| First-run win | Tool | What changes in the chat |
| --- | --- | --- |
| Less planning uncertainty | `adaptorch_route_topology` | Claude can explain whether the task should be singleton, pipeline, DAG, or ensemble before spending run budget. |
| Fewer failed long tasks | `adaptorch_run` | Large goals move through AdaptOrch routing, synthesis, and telemetry instead of one brittle pass. |
| Evidence without context switching | `adaptorch_get_artifacts` | Outputs, traces, and run proof come back into the Claude Code conversation. |
| Safer setup support | `adaptorch-mcp-doctor` | Users can paste redacted diagnostics without leaking tokens. |
| Fast install loop | `adaptorch-mcp-smoke` | Local MCP wiring is verified with `initialize` + `tools/list`. |

## Architecture

<p align="center">
  <img src="assets/mcp-flow.png" alt="AdaptOrch MCP route-run-evidence flow" width="100%">
</p>

## Packages

| Path | Package | Purpose |
| --- | --- | --- |
| `packages/adaptorch-mcp` | `adaptorch-mcp` | Python CLI wrapper around `adaptorch.mcp_server` |

The wrapper intentionally delegates runtime behavior to `adaptorch.mcp_server`. That keeps MCP tools, resources, prompts, safety checks, and transports aligned with the latest AdaptOrch core release.

## Quickstart

### Local development

```bash
git clone git@github.com:dmae97/Adaptorch-MCP.git
git clone git@github.com:dmae97/adaptorch.git  # alongside Adaptorch-MCP
cd Adaptorch-MCP
uv sync --all-packages --extra dev
uv run adaptorch-mcp --help
```

## stdio MCP

Use stdio for local clients such as Claude Code or desktop MCP hosts.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp --transport stdio --base-url https://adaptorch.ai.kr
```

## HTTP MCP

Use HTTP for local gateways, reverse proxies, or remote MCP clients.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<upstream-adaptorch-token>"
export ADAPTORCH_MCP_HTTP_AUTH_TOKEN="<client-facing-mcp-token>"

adaptorch-mcp \
  --transport http \
  --base-url https://adaptorch.ai.kr \
  --http-host 127.0.0.1 \
  --http-port 8765
```

Health check:

```bash
python - <<'PY'
import httpx
print(httpx.get('http://127.0.0.1:8765/mcp/health').json())
PY
```

## Claude Code MCP config

```json
{
  "mcpServers": {
    "adaptorch": {
      "command": "adaptorch-mcp",
      "args": [
        "--transport",
        "stdio",
        "--base-url",
        "https://adaptorch.ai.kr"
      ],
      "env": {
        "ADAPTORCH_CONTROL_PLANE_TOKEN": "${ADAPTORCH_CONTROL_PLANE_TOKEN}"
      }
    }
  }
}
```

More templates:

- `examples/claude_desktop_config.json`
- `examples/omk.mcp.json`
- `examples/mcp-http.env.example`

## Diagnostics

Print redacted local diagnostics:

```bash
adaptorch-mcp-doctor
adaptorch-mcp-doctor --json
```

Run a stdio smoke test. The token is passed through the child environment, not process arguments.

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.ai.kr
```

Expected output includes `adaptorch_plan_catalog` and the core AdaptOrch MCP tool surface.

## Tool surface

| Tool | Purpose |
| --- | --- |
| `adaptorch_run` | Submit an AdaptOrch task payload and optionally wait. |
| `adaptorch_get_run` | Read run summary by `run_id`. |
| `adaptorch_get_artifacts` | Read artifact metadata for a run. |
| `adaptorch_list_runs` | List recent runs. |
| `adaptorch_get_traces` | Read execution traces. |
| `adaptorch_cancel_run` | Request run cancellation. |
| `adaptorch_route_topology` | Locally route a DAG through AdaptOrch's topology router. |
| `adaptorch_server_metrics` | Read redacted MCP server metrics. |
| `adaptorch_capabilities` | Read synthesis modes, connectors, and server features. |
| `adaptorch_plan_catalog` | Read hosted plan catalog: Starter `$0`, Pro `$39`, Team `$149`. |

Read-only tools are safe candidates for MCP auto-approve. Keep `adaptorch_run` and `adaptorch_cancel_run` manually approved.

## Branding assets

- GitHub hero: `assets/readme-hero.png`
- GitHub flow diagram: `assets/mcp-flow.png`
- GPT-image-2.0 raster prompt brief: `docs/brand/gpt-image-2-brief.md`

## Public release checklist

Before publishing:

```bash
uv run ruff check packages/adaptorch-mcp
uv run mypy packages/adaptorch-mcp/src
uv run pytest packages/adaptorch-mcp/tests -q
uv run python -m build packages/adaptorch-mcp --outdir dist
uv publish --dry-run dist/*
```

Then follow `docs/publishing.md` for PyPI Trusted Publishing or token-based `uv publish`.

## Security

Never commit `.env`, API keys, bearer tokens, private keys, or MCP client tokens. See `SECURITY.md`.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
