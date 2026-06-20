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
- Do not commit secrets, local MCP auth tokens, or real tenant URLs in example configs.
- Keep examples client-agnostic and placeholder-based.
- Update `README.md`, `packages/adaptorch-mcp/README.md`, examples, and security/publication docs when transport, auth, env vars, auto-approval, or tool-surface behavior changes.

## Pull Request Checklist

- [ ] `python -m ruff check packages/adaptorch-mcp`
- [ ] `PYTHONPATH=packages/adaptorch-mcp/src python -m mypy packages/adaptorch-mcp/src`
- [ ] `PYTHONPATH=packages/adaptorch-mcp/src python -m pytest packages/adaptorch-mcp/tests -q`
- [ ] README/package README/examples updated when CLI or config behavior changes
- [ ] `SECURITY.md` and `PUBLICATION.md` updated when auth, transport, env vars, or example safety guidance changes
- [ ] P11–P19 accuracy wording remains engine-delegated and default-off unless benchmark evidence supports a deployment-specific profile
- [ ] No real tokens, private URLs, `.env*` files, prompts, traces, or artifacts in diffs
