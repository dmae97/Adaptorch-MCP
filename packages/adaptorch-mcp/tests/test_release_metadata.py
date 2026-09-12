"""Release boundaries: identity, ownership, and an unambiguous launcher."""
from __future__ import annotations

import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]


def test_distribution_ships_the_canonical_classicmate_license() -> None:
    metadata = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())
    project = metadata["project"]
    assert project["license"] == {
        "text": "Proprietary — Copyright ClassicMate. All rights reserved."
    }
    assert metadata["tool"]["setuptools"]["license-files"] == ["LICENSE"]
    assert (PACKAGE_ROOT / "LICENSE").read_bytes() == (REPO_ROOT / "LICENSE").read_bytes()


def test_wrapper_dependency_cannot_resolve_to_the_planned_codeless_meta_package() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == ["adaptorch[api]>=0.1.2,<0.2"]
    assert project["requires-python"] == ">=3.11,<3.13"


def test_wrapper_has_a_launcher_name_not_shared_with_the_engine() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())["project"]
    assert project["scripts"]["adaptorch-mcp-client"] == "adaptorch_mcp.cli:main"
    assert project["scripts"]["adaptorch-mcp"] == "adaptorch_mcp.cli:main"
