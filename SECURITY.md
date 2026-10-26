# Security Policy

## Supported Versions

| Version | Supported |
| --- | --- |
| `0.5.x` | yes |
| `0.4.x` | best effort |
| `< 0.4` | no |
| `main` | yes |

Security fixes target the latest public release and the `main` branch.

## Reporting a Vulnerability

Please report security issues privately by email: `ict03@rfems.com`.

Do not open a public issue for suspected secrets, authentication bypasses, transport vulnerabilities, prompt/artifact disclosure, or control-plane credential exposure. Expect an initial triage response within 3 business days for supported versions.

## Secret Handling

- Never commit `.env`, API keys, bearer tokens, private keys, or MCP client tokens.
- Example configs in this repository use placeholders or environment interpolation only.
- Keep real URLs and tokens in local, uncommitted config files.
- Production MCP HTTP should use a separate `ADAPTORCH_MCP_HTTP_AUTH_TOKEN` from the upstream AdaptOrch control-plane token.
- Prefer localhost binding for HTTP transport unless the endpoint is protected by a trusted reverse proxy and TLS.

## Transport Notes

- stdio is intended for local MCP clients.
- HTTP transport requires bearer auth and origin/protocol validation from the underlying AdaptOrch MCP server.
- Keep `ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES` bounded for public deployments.
- Set `ADAPTORCH_MCP_ALLOWED_ORIGINS` narrowly when browser or remote clients can reach HTTP/SSE.
- Avoid auto-approving run, artifact, and trace readers in shared or production MCP clients unless those payloads are sanitized.
- The built-in HTTP listener binds loopback only, caps concurrent connections at `ADAPTORCH_MCP_MAX_SSE_SUBSCRIBERS` plus 64, and omits the `server` header.
- Outbound SDK, CLI and connector HTTPS verifies certificates and hostnames and requires TLS 1.2 or newer. Ambient proxy variables and redirects are ignored, so credentials never follow a redirect or an unexpected proxy.
- Keep-alive connections are reused only for `GET`/`HEAD`. Run submission and cancellation always use a fresh connection and are never re-sent; a read is re-sent once only when its reused idle connection was already closed by the server.
- For stdio over SSH, keep tokens in the remote host environment rather than in the SSH command line, which other local users can see in the process list.

## Accuracy and Benchmark Data Hygiene

Engine algorithm controls (e.g. `ADAPTORCH_REPRODUCIBLE`, `ADAPTORCH_PAPER_SEMANTIC_WEIGHT`, `ADAPTORCH_ROUTER_ACCURACY_GATE`) are opt-in and engine-delegated; the wrapper does not implement these algorithms. When sharing accuracy reports, benchmark corpora, traces, artifacts, prompts, and outputs, remove tenant data, credentials, file-system secrets, and private source snippets first.
