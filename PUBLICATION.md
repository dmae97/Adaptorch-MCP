# Public Publication Checklist

Use this before making the repository public.

## Repository

- [ ] Confirm `LICENSE` and `NOTICE` are present.
- [ ] Confirm default branch protection and required CI checks.
- [ ] Confirm issue templates and security contact.
- [ ] Confirm all examples use placeholders, not real credentials.
- [ ] Run a secret scan before publishing.

## Package

- [ ] Decide whether `adaptorch` is available on PyPI.
- [ ] If not on PyPI, document GitHub install path clearly.
- [ ] Tag package releases from the monorepo root.
- [ ] Build package locally with `python -m build packages/adaptorch-mcp`.
- [ ] Verify console script: `adaptorch-mcp --help`.
- [ ] Verify diagnostics: `adaptorch-mcp-doctor --json`.

## MCP Smoke Tests

- [ ] stdio: `adaptorch-mcp-smoke --base-url <url>`.
- [ ] HTTP: `/mcp/health`, initialize, `tools/list`.
- [ ] Confirm `adaptorch_plan_catalog` appears if using AdaptOrch >= the pricing catalog MCP update.

## Public Safety

- [ ] No `.env*`, API keys, private keys, or tenant tokens.
- [ ] HTTP examples bind to `127.0.0.1` by default.
- [ ] Docs explain separate MCP HTTP auth token vs upstream control-plane token.
