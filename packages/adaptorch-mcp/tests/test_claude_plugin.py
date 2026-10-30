"""The Claude Code plugin ships only the public remote client and a public skill."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from adaptorch_mcp.thin_remote import CANDIDATE_TOOL_NAMES, REMOTE_TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "adaptorch"
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
SKILL = PLUGIN_ROOT / "skills" / "adaptorch" / "SKILL.md"
PUBLIC_TEXT = (SKILL, PLUGIN_ROOT / "README.md")

# Names that exist only in the private engine, its maintainer tooling or the `full`
# exposure profile. None of them may be advertised by the public plugin.
INTERNAL_TERMS = re.compile(
    r"full50|conformal|aeg[-_ ]?te|behavioral_ranking|edgar|theta_|route_topology|"
    r"get_traces|adaptorch_mcp_legacy|engine-check|exposure_profile[^\n]*\bfull\b",
    re.IGNORECASE,
)
CREDENTIAL = re.compile(r"\b(?:ado_(?:live|test)_\w+|ak_\w{6,}|sk-\w{8,}|ghp_\w{8,})")


def _json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _server() -> dict[str, Any]:
    servers = _json(MANIFEST)["mcpServers"]
    assert list(servers) == ["adaptorch"]
    server = servers["adaptorch"]
    assert isinstance(server, dict)
    return server


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_marketplace_lists_the_plugin_under_its_manifest_name() -> None:
    marketplace = _json(MARKETPLACE)
    manifest = _json(MANIFEST)

    assert marketplace["name"] == "adaptorch"
    assert marketplace["owner"]["name"]
    [entry] = marketplace["plugins"]
    assert entry["name"] == manifest["name"] == "adaptorch"
    assert entry["source"] == "./plugins/adaptorch"


def test_plugin_runs_the_published_remote_client_over_stdio() -> None:
    server = _server()
    args = server["args"]

    assert server["command"] == "uvx"
    assert args[-3:] == ["adaptorch-mcp-client", "--transport", "stdio"]
    assert not any(arg.startswith("--api-token") for arg in args)
    assert server["env"]["ADAPTORCH_MCP_EXPOSURE_PROFILE"] == "remote"


def test_plugin_version_range_admits_the_current_client_release() -> None:
    [requirement] = [arg for arg in _server()["args"] if arg.startswith("adaptorch-mcp>")]
    match = re.fullmatch(r"adaptorch-mcp>=([\d.]+),<([\d.]+)", requirement)
    assert match is not None, requirement
    project = tomllib.loads(
        (REPO_ROOT / "packages" / "adaptorch-mcp" / "pyproject.toml").read_text()
    )["project"]

    current = _version(project["version"])
    assert _version(match.group(1)) <= current < _version(match.group(2))


def test_api_key_is_a_sensitive_option_used_only_in_the_server_env() -> None:
    manifest = _json(MANIFEST)
    options = manifest["userConfig"]
    raw = MANIFEST.read_text(encoding="utf-8")

    assert options["api_token"]["sensitive"] is True
    assert set(re.findall(r"\$\{user_config\.(\w+)\}", raw)) == set(options)
    assert _server()["env"]["ADAPTORCH_CONTROL_PLANE_TOKEN"] == "${user_config.api_token}"


def test_public_text_names_only_remote_tools_and_documents_all_of_them() -> None:
    allowed = set(REMOTE_TOOL_NAMES) | set(CANDIDATE_TOOL_NAMES)
    skill = SKILL.read_text(encoding="utf-8")

    for path in PUBLIC_TEXT:
        named = set(re.findall(r"\badaptorch_[a-z_]+\b", path.read_text(encoding="utf-8")))
        assert named <= allowed, f"{path.name}: {sorted(named - allowed)}"
    assert set(REMOTE_TOOL_NAMES) <= set(re.findall(r"\badaptorch_[a-z_]+\b", skill))


def test_public_files_carry_no_internal_terms_or_credentials() -> None:
    files = [MARKETPLACE, *sorted(p for p in PLUGIN_ROOT.rglob("*") if p.is_file())]
    for path in files:
        text = path.read_text(encoding="utf-8")
        internal = INTERNAL_TERMS.search(text)
        assert internal is None, f"{path.relative_to(REPO_ROOT)}: {internal.group(0)!r}"
        assert CREDENTIAL.search(text) is None, path.relative_to(REPO_ROOT)


def test_skill_has_frontmatter_claude_code_can_load() -> None:
    text = SKILL.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match is not None
    fields = dict(line.split(": ", 1) for line in match.group(1).splitlines())

    assert fields["name"] == "adaptorch"
    assert len(fields["description"]) > 40
