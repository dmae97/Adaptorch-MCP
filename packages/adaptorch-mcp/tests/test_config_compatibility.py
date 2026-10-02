from __future__ import annotations

import pytest

from adaptorch_mcp.config import from_environment


@pytest.mark.parametrize(
    ("env_values", "explicit", "expected"),
    [
        ({}, None, "https://adaptorch.com"),
        (
            {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://legacy.invalid"},
            None,
            "https://legacy.invalid",
        ),
        (
            {"ADAPTORCH_CONTROL_PLANE_BASE_URL": " https://legacy.invalid "},
            None,
            "https://legacy.invalid",
        ),
        ({"ADAPTORCH_CONTROL_PLANE_BASE_URL": "  "}, None, "https://adaptorch.com"),
        ({"ADAPTORCH_CONTROL_PLANE_URL": "https://alias.invalid"}, None, "https://adaptorch.com"),
        (
            {
                "ADAPTORCH_CONTROL_PLANE_URL": "https://alias.invalid",
                "ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://legacy.invalid",
            },
            None,
            "https://legacy.invalid",
        ),
        (
            {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://legacy.invalid"},
            "https://explicit.invalid",
            "https://explicit.invalid",
        ),
        (
            {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "invalid"},
            "https://explicit.invalid",
            "https://explicit.invalid",
        ),
    ],
)
def test_public_legacy_origin_precedence(env_values, explicit, expected):
    config = from_environment(
        {"ADAPTORCH_CONTROL_PLANE_TOKEN": "ado_fixture", **env_values}, base_url=explicit
    )
    assert config.client.api_url == expected


def test_invalid_legacy_origin_never_silently_falls_back():
    with pytest.raises(ValueError):
        from_environment(
            {
                "ADAPTORCH_CONTROL_PLANE_TOKEN": "ado_fixture",
                "ADAPTORCH_CONTROL_PLANE_BASE_URL": "ftp://invalid.example",
            }
        )
