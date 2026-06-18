# Contributing

Thanks for improving AdaptOrch MCP.

## Development Setup

```bash
uv sync --all-packages --extra dev
uv run pytest
```

For a local checkout without uv workspace resolution:

```bash
PYTHONPATH=packages/adaptorch-mcp/src python -m pytest packages/adaptorch-mcp/tests -q
```

## Rules

- Keep runtime logic in AdaptOrch unless there is a strong packaging reason to add code here.
- Do not duplicate MCP tool definitions from `adaptorch.mcp_server`.
- Add tests for wrapper behavior and public contract changes.
- Do not commit secrets or local MCP auth tokens.
- Keep examples client-agnostic and placeholder-based.

## Pull Request Checklist

- [ ] `python -m ruff check packages/adaptorch-mcp`
- [ ] `PYTHONPATH=packages/adaptorch-mcp/src python -m mypy packages/adaptorch-mcp/src`
- [ ] `PYTHONPATH=packages/adaptorch-mcp/src python -m pytest packages/adaptorch-mcp/tests -q`
- [ ] README/examples updated when CLI or config behavior changes
- [ ] No real tokens in diffs
