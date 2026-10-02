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

## MCP0.6 candidate boundary

See the README for supported credentials, stdio framing, nine-tool exposure, error
projection, resource/prompt allowlists, and post-connect deadline limitations.

The endpoint must be an explicitly configured trusted AdaptOrch-compatible HTTPS origin.
A server can still lie about first-use tenant identity or semantic run status; local
projection is not independent proof of hosted correctness or execution. Authentication
and access control remain hosted-service responsibilities.

Do not place tenant/provider keys in tool arguments, prompts, URLs, schemas or examples.
No keyless provider, shell key-command, fallback provider, arbitrary headers, tenant
argument override, downloaded artifact execution, trace or topology exposure is supported.

Production/service and provider calls require a separately authorized test tenant and
scope. Offline synthetic tests do not establish production behavior.
