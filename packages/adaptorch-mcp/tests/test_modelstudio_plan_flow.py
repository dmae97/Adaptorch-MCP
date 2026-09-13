"""SDK and hardened MCP reach the real control-plane engine; only provider HTTP is fake."""

from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib import request
from urllib.response import addinfourl
from uuid import uuid4

import httpx
import pytest
from adaptorch import providers
from adaptorch.cloud_auth import CloudAuthService
from adaptorch.control_plane import ControlPlaneService, create_control_plane_app
from adaptorch.n8n_connector import ControlPlaneProviderCredential, N8nConnectorConfig
from fastapi.testclient import TestClient

from adaptorch_client import AdaptOrchClient, ClientConfig, ProviderCredential
from adaptorch_mcp.control_plane_backend import SafeControlPlaneConnector
from adaptorch_mcp.hardening import HardenedMCPServer
from adaptorch_mcp.security_policy import REMOTE_EXPOSURE_PROFILE

plan = pytest.importorskip(
    "adaptorch.modelstudio_plan", reason="installed engine predates ModelStudio Token Plan support"
)
MODELSTUDIO_PLAN_PROVIDER: str = plan.MODELSTUDIO_PLAN_PROVIDER
MODELSTUDIO_PLAN_URL: str = plan.MODELSTUDIO_PLAN_URL
MODEL = "deepseek-v4-flash-0731"
SECRET = "sk-sp-local-plan-test-not-a-real-key"


class WireResponse(addinfourl):
    msg = "local control-plane response"


def test_sdk_and_mcp_reach_plan_without_migrating_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in (
        "ADAPTORCH_SUPABASE_JWT_SECRET",
        "SUPABASE_JWT_SECRET",
        "ADAPTORCH_EXECUTION_PROVIDER",
        "ADAPTORCH_EXECUTION_ENSEMBLE",
        "ADAPTORCH_EXECUTION_JUDGE",
        "ADAPTORCH_ALLOWED_API_HOSTS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ADAPTORCH_HOSTED", "true")
    monkeypatch.setattr(providers, "_CLIENT_POOL", {})
    cloud = CloudAuthService()
    tenant_key, _ = cloud.create_api_key(tenant_id="plan-test", plan_level="starter")
    service = ControlPlaneService(artifact_root=tmp_path / "artifacts", local_admin_bootstrap=False)
    app = create_control_plane_app(
        service=service,
        auth_token="unused-test-admin",
        cloud_auth_service=cloud,
    )
    provider_requests: list[httpx.Request] = []
    api_requests: list[request.Request] = []

    def provider_reply(req: httpx.Request) -> httpx.Response:
        provider_requests.append(req)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    def provider_client(
        key: providers.ProviderClientPoolKey,
        timeout: httpx.Timeout,
    ) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(provider_reply), trust_env=False)
        providers._CLIENT_POOL[key] = client
        return client

    monkeypatch.setattr(providers, "_get_or_create_client", provider_client)
    with TestClient(app) as api:

        def open_api(_handler: request.AbstractHTTPHandler, req: request.Request) -> WireResponse:
            assert req.host == "engine.test"
            api_requests.append(req)
            body = req.data
            assert body is None or isinstance(body, bytes)
            response = api.request(
                req.get_method(),
                req.selector,
                content=body,
                headers=dict(req.header_items()),
            )
            headers = Message()
            for name, value in response.headers.items():
                headers[name] = value
            return WireResponse(
                BytesIO(response.content), headers, req.full_url, response.status_code
            )

        monkeypatch.setattr(request.HTTPHandler, "http_open", open_api)
        monkeypatch.setattr(request.HTTPSHandler, "https_open", open_api)
        sdk = AdaptOrchClient(ClientConfig("https://engine.test", tenant_key))
        submitted = sdk.submit_run(
            {
                "payload": {"subtasks": [{"id": "v1", "description": "Say ready"}]},
                "synthesis_mode": "paper",
            },
            str(uuid4()),
            provider_credential=ProviderCredential(MODELSTUDIO_PLAN_PROVIDER, MODEL, SECRET),
        )
        observed = sdk.get_run(submitted.run_id)
        assert observed.status == "SUCCEEDED"

        mcp = HardenedMCPServer(
            backend=SafeControlPlaneConnector(
                N8nConnectorConfig(
                    base_url="https://engine.test",
                    api_token=tenant_key,
                    provider_credential=ControlPlaneProviderCredential(
                        MODELSTUDIO_PLAN_PROVIDER,
                        MODEL,
                        SECRET,
                    ),
                )
            ),
            exposure_profile=REMOTE_EXPOSURE_PROFILE,
        )
        response = mcp.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "adaptorch_run",
                    "arguments": {
                        "prompt": "Say ready",
                        "synthesis_mode": "paper",
                        "wait_for_terminal": True,
                    },
                },
            }
        )
        assert response is not None and "error" not in response
        assert response["result"]["isError"] is False
        result = json.loads(response["result"]["content"][0]["text"])
        assert result["status"] == "SUCCEEDED"
        assert SECRET not in json.dumps(response)

    assert len(provider_requests) == 2
    for req in provider_requests:
        assert str(req.url) == MODELSTUDIO_PLAN_URL
        assert req.headers["authorization"] == f"Bearer {SECRET}"
        assert json.loads(req.content)["model"] == MODEL
        assert SECRET not in req.content.decode()
    for req in api_requests:
        headers = {name.lower(): value for name, value in req.header_items()}
        if req.get_method() == "POST":
            assert headers["x-provider"] == MODELSTUDIO_PLAN_PROVIDER
            assert headers["x-provider-key"] == SECRET
            body = req.data
            assert isinstance(body, bytes)
            assert SECRET not in body.decode()
        else:
            assert not any(name.startswith("x-provider") for name in headers)
    for path in (tmp_path / "artifacts").rglob("*.json"):
        assert SECRET not in path.read_text()
