# Security Policy

## Supported Versions

Security fixes target the latest public release and the `main` branch.

## Reporting a Vulnerability

Please report security issues privately by email: `ict03@rfems.com`.

Do not open a public issue for suspected secrets, authentication bypasses, transport vulnerabilities, or control-plane credential exposure.

## Secret Handling

- Never commit `.env`, API keys, bearer tokens, private keys, or MCP client tokens.
- Example configs in this repository use placeholder values only.
- Production MCP HTTP should use a separate `ADAPTORCH_MCP_HTTP_AUTH_TOKEN` from the upstream AdaptOrch control-plane token.
- Prefer localhost binding for HTTP transport unless the endpoint is protected by a trusted reverse proxy and TLS.

## Transport Notes

- stdio is intended for local MCP clients.
- HTTP transport requires bearer auth and origin/protocol validation from the underlying AdaptOrch MCP server.
- Keep `ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES` bounded for public deployments.
