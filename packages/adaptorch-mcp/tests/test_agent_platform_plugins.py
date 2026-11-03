"""Distribution metadata must resolve to the same public client and usable skill."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from adaptorch_mcp.thin_remote import CANDIDATE_TOOL_NAMES, REMOTE_TOOL_NAMES
from adaptorch_mcp.thin_runtime import provider_credential_from_env

ROOT = Path(__file__).resolve().parents[3]
GROK_PLUGIN = ROOT / "plugins" / "adaptorch-grok"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_kimi_and_grok_reference_the_same_published_remote_client() -> None:
    project = tomllib.loads((ROOT / "packages/adaptorch-mcp/pyproject.toml").read_text())
    expected_version = project["project"]["version"]
    kimi = _json(ROOT / "kimi.plugin.json")
    grok = _json(GROK_PLUGIN / ".mcp.json")
    servers = [kimi["mcpServers"]["adaptorch"], grok["mcpServers"]["adaptorch"]]

    for server in servers:
        assert server["command"] == "uvx"
        assert server["args"] == [
            "--python",
            "3.12",
            "--from",
            f"adaptorch-mcp=={expected_version}",
            "adaptorch-mcp-client",
            "--transport",
            "stdio",
        ]
        assert server["env"]["ADAPTORCH_MCP_EXPOSURE_PROFILE"] == "remote"
        assert not any("token" in arg or "key" in arg for arg in server["args"])

    # Kimi merges its own parent process environment; do not overwrite unset keys with
    # literal expansion strings. Grok resolves these optional variables itself.
    assert set(servers[0]["env"]) == {"ADAPTORCH_MCP_EXPOSURE_PROFILE"}
    for name in (
        "ADAPTORCH_CONTROL_PLANE_TOKEN",
        "ADAPTORCH_MCP_PROVIDER",
        "ADAPTORCH_MCP_PROVIDER_MODEL",
        "ADAPTORCH_MCP_PROVIDER_API_KEY",
    ):
        assert servers[1]["env"][name] == "${" + name + ":-}"


def test_marketplace_and_kimi_skill_paths_stay_inside_the_package() -> None:
    marketplace = _json(ROOT / ".grok-plugin/marketplace.json")
    [entry] = marketplace["plugins"]
    manifest = _json(GROK_PLUGIN / ".grok-plugin/plugin.json")
    assert entry["name"] == manifest["name"] == "adaptorch"
    assert (ROOT / entry["source"]).resolve() == GROK_PLUGIN

    kimi = _json(ROOT / "kimi.plugin.json")
    skill_dir = (ROOT / kimi["skills"]).resolve()
    assert skill_dir.is_relative_to(ROOT)
    skill = (skill_dir / "adaptorch/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: adaptorch\n")
    names = set(re.findall(r"\badaptorch_[a-z_]+\b", skill))
    assert names <= set(REMOTE_TOOL_NAMES) | set(CANDIDATE_TOOL_NAMES)


def test_optional_provider_fields_are_empty_for_read_only_calls() -> None:
    assert provider_credential_from_env({}) is None
    assert provider_credential_from_env(
        {
            "ADAPTORCH_MCP_PROVIDER": "",
            "ADAPTORCH_MCP_PROVIDER_MODEL": "",
            "ADAPTORCH_MCP_PROVIDER_API_KEY": "",
        }
    ) is None
