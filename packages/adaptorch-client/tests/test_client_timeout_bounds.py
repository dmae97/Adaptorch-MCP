"""Client timeout values must be representable by the platform's blocking I/O."""

import pytest

from adaptorch_client import ClientConfig


@pytest.mark.parametrize("seconds", [True, 0, float("nan"), float("inf"), 10**400, 1e20])
def test_invalid_client_timeout_is_rejected_before_network(seconds: float) -> None:
    with pytest.raises(ValueError):
        ClientConfig("https://api.example.test", "ado_test", timeout_seconds=seconds)
