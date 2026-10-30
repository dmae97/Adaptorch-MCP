# AdaptOrch MCP stdio server, built from one pinned public commit.
# No credentials are baked in. Without ADAPTORCH_CONTROL_PLANE_TOKEN the server
# answers initialize/ping/tools/list only; every tool call fails closed.
FROM python:3.12-slim AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ARG ADAPTORCH_MCP_COMMIT=864a4ef3b21ab21d050fe5aa9c2846f93668828a
ARG SOURCE=git+https://github.com/dmae97/Adaptorch-MCP@${ADAPTORCH_MCP_COMMIT}
RUN pip wheel --no-cache-dir --wheel-dir /wheels \
    "adaptorch-client @ ${SOURCE}#subdirectory=packages/adaptorch-client" \
    "adaptorch-mcp @ ${SOURCE}#subdirectory=packages/adaptorch-mcp"

FROM python:3.12-slim
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels adaptorch-mcp \
    && rm -rf /wheels \
    && useradd --create-home --uid 10001 adaptorch
USER adaptorch
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["adaptorch-mcp", "--transport", "stdio"]
