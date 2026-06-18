# adaptorch-mcp

Installable Python wrapper for the AdaptOrch MCP server.

The package intentionally delegates to `adaptorch.mcp_server` so MCP behavior stays aligned with AdaptOrch core.

## Install

```bash
pip install adaptorch-mcp
```

If AdaptOrch is not published to your package index yet:

```bash
pip install "adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git"
pip install adaptorch-mcp
```

## Run

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp --transport stdio --base-url https://adaptorch.ai.kr
```

## Diagnostics

```bash
adaptorch-mcp-doctor --json
```

The doctor command reports package availability, expected MCP tools, and environment variable presence without printing token values.

## stdio smoke test

```bash
export ADAPTORCH_CONTROL_PLANE_TOKEN="<your-token>"
adaptorch-mcp-smoke --base-url https://adaptorch.ai.kr
```

## HTTP app factory

```python
from adaptorch_mcp import create_default_mcp_http_app

app = create_default_mcp_http_app()
```
