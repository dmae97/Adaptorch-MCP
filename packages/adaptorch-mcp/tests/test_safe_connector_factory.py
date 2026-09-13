"""The public factory must actually use the one-attempt transport."""

import pytest

from adaptorch_mcp.control_plane_backend import SafeControlPlaneConnector
from adaptorch_mcp.hardening import build_hardened_mcp_server
from adaptorch_mcp.security_policy import REMOTE_EXPOSURE_PROFILE


def test_public_factory_installs_the_safe_parent_compatible_backend() -> None:
    # Given normal factory configuration, without making an HTTP request.
    server = build_hardened_mcp_server(
        base_url="https://api.example.test",
        api_token="ado_synthetic",
        timeout_seconds=1,
        exposure_profile=REMOTE_EXPOSURE_PROFILE,
        allow_insecure=False,
    )
    # Then parent task planning delegates its network I/O to the safe transport.
    assert isinstance(server._backend, SafeControlPlaneConnector)
    assert server._backend._config.retry_policy.max_attempts == 1


@pytest.mark.parametrize("seconds", [True, 0, float("nan"), float("inf"), 10**400, 1e20])
def test_factory_rejects_unusable_timeouts_before_network(seconds: float) -> None:
    with pytest.raises(ValueError):
        build_hardened_mcp_server(
            base_url="https://api.example.test",
            api_token="ado_test",
            timeout_seconds=seconds,
            exposure_profile=REMOTE_EXPOSURE_PROFILE,
            allow_insecure=False,
        )
