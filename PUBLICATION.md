# Publication gate (not authorization)

Version 0.6.0 is a local migration candidate. No release, upload, merge or production test
has been authorized by creating this prototype. Verify the complete source diff, all
runtime dependencies and wheel contents; disclose the breaking migration; pass Python
3.11 and 3.12 clean-install tests; complete source-backed synthetic hosted-contract tests;
then obtain separate publication authorization. Keep private full/local-engine usage separate.

The isolated runtime gate must contain only `adaptorch-mcp==0.6.0`, the official public
`adaptorch-client==0.1.2` wheel and ordinary packaging bootstrap, with empty HOME, disabled
user-site/config, no Git credential, no editable install and no private source override.
Never confuse a build tool installed in a development environment with clean runtime proof.

## Repository release checks

- Retain ClassicMate LICENSE/NOTICE and verify every built wheel's ownership metadata
- Run inherited E,F,I,UP,B lint, strict typing and all public package tests
- Gate every public wheel including MCP against private imports/dependencies
- Run Python3.11/3.12 clean installed-wheel initialization/discovery/read/submit fixtures
- Keep Git/workspace credentials out of clean public runtime proof
- Inspect examples/docs for real keys, private artifacts and unsupported legacy setup advice
- Obtain publication approval; do not modify publisher credentials or permissions
- No accuracy improvements may be claimed without the existing n>=50/Wilcoxon/95%CI gate
