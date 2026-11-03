---
name: adaptorch
description: Use when the user explicitly requests an AdaptOrch run, its status, artifacts, cancellation, plan, or usage through the configured AdaptOrch MCP server.
---

# AdaptOrch

AdaptOrch is a hosted service. Its public MCP client forwards requests to the service;
the plugin does not contain the orchestration engine. Use only the tools and parameter
schemas actually advertised by the connected server.

## Before calling tools

- Submit `adaptorch_run` only when the user requests an AdaptOrch run. A submission can
  consume plan quota, and provider tokens can incur separate charges. Explain this before
  submission. Ask before sending private code or other sensitive context unless the user
  has already authorized that scope. Do not include credentials or secrets in inputs.
- If service authentication or model credentials are missing, explain how to configure
  them outside chat using the plugin's installation guide. Do not request secrets in chat,
  tool arguments, files committed to a repository, or screenshots.
- The current chat model is not automatically available to the hosted service. A model
  run may require a separately configured provider, model ID and provider key.
- Use `adaptorch_capabilities` before selecting optional modes. Do not invent parameters.

## Workflows

- Use `adaptorch_usage` and `adaptorch_plan_catalog` for plan information, and
  `adaptorch_list_runs` or `adaptorch_get_run` for existing runs.
- For a requested task, use `adaptorch_run`; for long work submit without waiting and
  poll `adaptorch_get_run` by its returned ID. Do not blindly resubmit after a timeout:
  the original submission may have succeeded. Check existing runs first.
- Use `adaptorch_get_artifacts` to retrieve available artifacts. Cancel a running task
  with `adaptorch_cancel_run` only when the user requests cancellation.
- Use any candidate-verification tools only when actually advertised by the server.

Report the returned status, available artifacts, checks and their limits. A completed run,
receipt or passing check is not proof of correctness or approval to deploy. Preserve
failed, timed-out and unknown states. Never invent an artifact or verification result.
