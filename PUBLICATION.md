# Public Publication Checklist

Use this before making the repository public or cutting a package release.

## Repository

- [ ] Confirm `LICENSE` and `NOTICE` are present.
- [ ] Confirm default branch protection and required CI checks.
- [ ] Confirm issue templates and security contact.
- [ ] Confirm all examples use placeholders or environment interpolation, not real credentials.
- [ ] Run a redacted secret scan and attach the output to release evidence:

```bash
gitleaks detect --source . --redact
```

If `gitleaks` is unavailable, run the project-approved equivalent and keep the output redacted.

## Package

- [ ] Decide whether `adaptorch` is available on PyPI.
- [ ] If not on PyPI, document the GitHub install path clearly.
- [ ] Verify `packages/adaptorch-mcp/pyproject.toml` version matches `adaptorch_mcp.__version__`.
- [ ] Tag package releases from the monorepo root.
- [ ] Build package locally with `python -m build packages/adaptorch-mcp`.
- [ ] Verify console script: `adaptorch-mcp --help`.
- [ ] Verify diagnostics: `adaptorch-mcp-doctor --json`.

## Documentation and Environment Coverage

- [ ] README and package README cover install, stdio, HTTP, doctor, smoke, examples, and the tool surface.
- [ ] Examples cover public env vars with placeholders: upstream token/base URL, HTTP auth token, allowed origins, max payload, request timeout, SSE subscribers, and accuracy profile overrides.
- [ ] Accuracy docs state that `ADAPTORCH_ACCURACY_PROFILE` defaults to `off` and that `balanced`/`max_accuracy` are opt-in per deployment.
- [ ] P11–P19 wording is engine-delegated; the wrapper must not claim duplicated algorithm implementations.
- [ ] Auto-approve guidance distinguishes trusted local clients from shared or production clients.

## MCP Smoke Tests

- [ ] stdio: `adaptorch-mcp-smoke --base-url <url>`.
- [ ] HTTP: `/mcp/health`, initialize, `tools/list`.
- [ ] Confirm `adaptorch_plan_catalog` appears if using AdaptOrch >= the pricing catalog MCP update.

## Public Safety

- [ ] No `.env*`, API keys, private keys, tenant tokens, or MCP client tokens.
- [ ] HTTP examples bind to `127.0.0.1` by default.
- [ ] Docs explain the separate MCP HTTP auth token vs upstream control-plane token.
- [ ] Benchmark corpora, prompts, traces, and artifacts are sanitized before sharing release evidence.
