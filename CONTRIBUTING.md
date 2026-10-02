# Contributing

Thanks for improving AdaptOrch MCP.

## Development Setup

```bash
uv sync --locked --all-packages --extra dev
uv run pytest
```

For a local checkout without uv workspace resolution:

```bash
PYTHONPATH=packages/adaptorch-mcp/src python -m pytest packages/adaptorch-mcp/tests -q
```

## Rules

- Keep remote transport and local exposure policy in the public MCP client; routing, synthesis and provider execution stay hosted.
- Never import or install the private `adaptorch` engine. Validate the hosted tool inventory against the fixed public allowlist; depend only on the published SDK.
- Add socket-blocked tests for bridge policy, public contracts and installed-wheel behavior. Private-engine integration remains a separate fixture gate.
- Do not commit secrets, local MCP auth tokens, or real tenant URLs in example configs.
- Keep examples client-agnostic and placeholder-based.
- Update `README.md`, `packages/adaptorch-mcp/README.md`, examples, and security/publication docs when transport, auth, env vars, auto-approval, or tool-surface behavior changes.

## Pull Request Checklist

- [ ] `python -m ruff check packages/adaptorch-mcp`
- [ ] `PYTHONPATH=packages/adaptorch-mcp/src python -m mypy packages/adaptorch-mcp/src`
- [ ] `PYTHONPATH=packages/adaptorch-mcp/src python -m pytest packages/adaptorch-mcp/tests -q`
- [ ] README/package README/examples updated when CLI or config behavior changes
- [ ] `SECURITY.md` and `PUBLICATION.md` updated when auth, transport, env vars, or example safety guidance changes
- [ ] Documented MCP options and exposed contracts match the public client and socket-blocked tests; do not install a private engine for this check. No accuracy/benchmark improvement numbers without n>=50 + Wilcoxon + 95% CI
- [ ] No real tokens, private URLs, `.env*` files, prompts, traces, or artifacts in diffs
