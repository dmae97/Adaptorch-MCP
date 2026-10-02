"""Release boundaries: identity, ownership, and an unambiguous launcher."""
from __future__ import annotations

import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]


def test_distribution_ships_the_canonical_classicmate_license() -> None:
    metadata = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())
    project = metadata["project"]
    assert project["license"] == "LicenseRef-Proprietary"
    assert project["authors"] == [{"name": "ClassicMate"}]
    assert project["license-files"] == ["LICENSE"]
    assert (PACKAGE_ROOT / "LICENSE").read_bytes() == (REPO_ROOT / "LICENSE").read_bytes()


def test_remote_bridge_depends_only_on_public_sdk() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == ["adaptorch-client==0.1.2"]
    assert project["requires-python"] == ">=3.11,<3.13"


def test_wrapper_has_a_launcher_name_not_shared_with_the_engine() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())["project"]
    assert project["scripts"]["adaptorch-mcp-client"] == "adaptorch_mcp.cli:main"
    assert "adaptorch-mcp" not in project["scripts"]
