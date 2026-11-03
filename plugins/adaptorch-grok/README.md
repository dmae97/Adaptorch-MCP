# AdaptOrch plugin for Grok Build

This plugin supplies an AdaptOrch skill and configures the published remote MCP client.
It does not ship the private engine. Install and credential instructions, including the
separate Grok Bot review process, are in
[agent platform integrations](../../docs/agent-platform-integrations.md).

```bash
grok plugin marketplace add dmae97/Adaptorch-MCP
grok plugin install adaptorch --trust
```

The service key and model-provider settings are taken from the environment of the Grok
process. A model run can consume plan quota and separately billed provider tokens. Review
the plugin before granting trust and do not send secrets in chat or task content.
