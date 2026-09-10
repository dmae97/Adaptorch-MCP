"""Real local HTTP → current engine API, without executing any model call."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from client_test_support import CapturedRequest, LocalAPIServer, ResponsePlan

from adaptorch_client import AdaptOrchAPIError, AdaptOrchClient, ClientConfig

pytest.importorskip("adaptorch.control_plane")
from adaptorch.cloud_auth import CloudAuthService
from adaptorch.control_plane import ControlPlaneService, create_control_plane_app
from fastapi.testclient import TestClient

RUN_SPEC = {"payload": {"subtasks": [{"id": "one", "description": "synthetic test only"}]}}
REQUEST_ID = "11111111-1111-4111-8111-111111111111"


@dataclass(frozen=True, slots=True)
class HostedFixture:
    wire: LocalAPIServer
    client: AdaptOrchClient
    service: ControlPlaneService
    api_key: str = field(repr=False)


@pytest.fixture()
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[HostedFixture]:
    monkeypatch.setenv("ADAPTORCH_HOSTED", "true")
    for name in (
        "ADAPTORCH_EXECUTION_PROVIDER",
        "ADAPTORCH_EXECUTION_MODEL",
        "ADAPTORCH_EXECUTION_ENSEMBLE",
        "ADAPTORCH_EXECUTION_JUDGE",
        "ADAPTORCH_PLATFORM_KEY_PLANS",
        "SUPABASE_JWT_SECRET",
        "ADAPTORCH_SUPABASE_JWT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    # Exercise admission and all wire contracts, never an engine/model dispatch.
    async def queued_only(self: ControlPlaneService, run_id: str) -> None:
        return None

    monkeypatch.setattr(ControlPlaneService, "execute_run_async", queued_only)
    service = ControlPlaneService(
        artifact_root=tmp_path / "artifacts",
        state_path=tmp_path / "runs.json",
        local_admin_bootstrap=False,
    )
    cloud = CloudAuthService()
    key, _ = cloud.create_api_key(tenant_id="sdk-fixture", plan_level="starter")
    app = create_control_plane_app(
        service=service, auth_token="test-admin", cloud_auth_service=cloud
    )
    with TestClient(app) as http:

        def respond(request: CapturedRequest) -> ResponsePlan:
            response = http.request(
                request.method, request.path, headers=request.headers, content=request.body or None
            )
            return ResponsePlan(
                response.status_code, response.content, {"Content-Type": "application/json"}
            )

        wire = LocalAPIServer(responder=respond)
        wire.start()
        try:
            client = AdaptOrchClient(ClientConfig(api_url=wire.api_url, api_key=key))
            yield HostedFixture(wire, client, service, key)
        finally:
            wire.close()


def test_public_mcp_wrapper_is_wired_to_actual_hosted_rest_routes(hosted: HostedFixture) -> None:
    hardening = pytest.importorskip("adaptorch_mcp.hardening")
    from adaptorch_client import ProviderCredential

    wrapper = hardening.build_hardened_mcp_server(
        base_url=hosted.wire.api_url,
        api_token=hosted.api_key,
        timeout_seconds=2,
        allow_insecure=True,
        exposure_profile="remote",
        provider_credential=ProviderCredential("openai", "synthetic-model", "fixture-key"),
    )

    def call(name: str, arguments: dict | None = None) -> dict:
        response = wrapper.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        assert response is not None and "error" not in response, response
        assert not response["result"].get("isError"), response
        return json.loads(response["result"]["content"][0]["text"])

    for name in (
        "adaptorch_capabilities",
        "adaptorch_plan_catalog",
        "adaptorch_server_metrics",
        "adaptorch_usage",
    ):
        assert call(name)
    run = call(
        "adaptorch_run",
        {"prompt": "local fixture", "wait_for_terminal": False, "synthesis_mode": "auto"},
    )
    run_id = run["run_id"]
    assert call("adaptorch_get_run", {"run_id": run_id})["run_id"] == run_id
    assert call("adaptorch_get_artifacts", {"run_id": run_id})["artifacts"] == {}
    assert call("adaptorch_list_runs")["items"][0]["run_id"] == run_id
    assert call("adaptorch_cancel_run", {"run_id": run_id})["error_class"] == "user_cancelled"


def test_sdk_discovery_reaches_the_engine_with_tenant_auth(hosted: HostedFixture) -> None:
    assert "runs" in hosted.client.capabilities().features
    assert hosted.client.whoami().project_id == "sdk-fixture"


def test_sdk_surfaces_the_hosted_byok_refusal(hosted: HostedFixture) -> None:
    with pytest.raises(AdaptOrchAPIError) as caught:
        hosted.client.submit_run(RUN_SPEC, REQUEST_ID)
    assert caught.value.status_code == 401
    assert caught.value.code == "byok_credentials_required"
    assert "X-Provider-Key" in str(caught.value)
    assert hosted.client.list_runs().items == ()


def test_sdk_reads_the_actual_hosted_artifact_map(hosted: HostedFixture) -> None:
    record, _ = hosted.service.create_or_get_run(
        payload=RUN_SPEC["payload"], tenant_id="sdk-fixture"
    )
    result = hosted.client.list_artifacts(record.run_id)
    assert result.run_id == record.run_id
    assert result.items == ()
    assert result.to_payload() == {"run_id": record.run_id, "artifacts": {}}


def test_sdk_byok_submit_retry_read_evidence_and_cancel_are_wired(hosted: HostedFixture) -> None:
    from adaptorch_client import ProviderCredential

    credential = ProviderCredential(
        provider="openai", model="synthetic-model", api_key="test-provider-secret"
    )
    created = hosted.client.submit_run(RUN_SPEC, REQUEST_ID, provider_credential=credential)
    replayed = hosted.client.submit_run(RUN_SPEC, REQUEST_ID, provider_credential=credential)
    assert replayed.run_id == created.run_id
    assert hosted.client.get_run(created.run_id).status == "QUEUED"
    assert [item.run_id for item in hosted.client.list_runs().items] == [created.run_id]
    assert hosted.client.get_evidence(created.run_id).run_id == created.run_id
    cancelled = hosted.client.cancel_run(created.run_id)
    assert cancelled.status == "FAILED"
    assert cancelled.to_payload()["error_class"] == "user_cancelled"
    posts = [request for request in hosted.wire.requests if request.method == "POST"]
    assert len(posts) == 2
    assert all(
        {key.lower(): value for key, value in request.headers.items()}["x-provider-key"]
        == credential.api_key
        for request in posts
    )
    assert all(
        not any(name.lower().startswith("x-provider") for name in request.headers)
        for request in hosted.wire.requests
        if request.method != "POST"
    )
