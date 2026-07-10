# AdaptOrch MCP Engineering Constitution

Version: 1.0
Last updated: 2026-07-10
Primary sources: parent repository `../Architecture.md`, `../src/adaptorch/`, and this repository's package contract

## 1. Parent Algorithm Parity

- The parent AdaptOrch repository is the source of truth for routing, synthesis, verification, budget, and result contracts.
- The public MCP wrapper must not fork or duplicate those algorithms.
- Compatibility changes must fail closed when the installed parent runtime lacks the required MCP contract.

## 2. Remote Algorithm Boundary

- Hosted/default operation keeps proprietary algorithm execution behind the control plane.
- Local topology/trace oracles are not exposed by the hardened profile.
- Obfuscation is not treated as a security boundary; deployed Python source can be inspected.

## 3. Security by Default

- Non-loopback control-plane traffic requires HTTPS unless the operator explicitly opts into insecure development transport.
- HTTP MCP transport requires a client-facing token distinct from the upstream control-plane token.
- Tokens, credentials, raw prompts, `.env` contents, and algorithm-sensitive traces must not appear in diagnostics or errors.
- External input is validated at the CLI/MCP boundary and failures are deny-by-default.

## 4. Compatibility and Scope

- Preserve existing full/local behavior only behind an explicit opt-in exposure profile.
- Prefer additive, reversible patches; no unrelated refactors or new dependencies.
- Never modify lockfiles without explicit approval.

## 5. Result and Evidence Contracts

- Preserve parent status values `OK`, `DEGRADED`, and `FAILED`.
- Every security behavior requires a regression test that fails when the guard is removed.
- Completion requires Ruff, mypy, pytest, and package build evidence.

## 6. Honest Security Claims

- Never claim that reverse engineering is impossible.
- Claim only measurable controls: reduced oracle surface, remote execution boundary, TLS enforcement, token separation, redaction, and compatibility checks.
