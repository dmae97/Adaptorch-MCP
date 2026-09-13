from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_REPOSITORY = "https://github.com/dmae97/Adaptorch-MCP"
PUBLIC_LICENSE = f"{PUBLIC_REPOSITORY}/blob/main/LICENSE"
CANONICAL_LICENSE_SHA256 = "9d3160a503b42e1e7014f8cbcd322ef869d454014b966748ea62d49178e2be91"
PACKAGE_ROOTS = (
    REPO_ROOT / "packages" / "adaptorch-client",
    REPO_ROOT / "packages" / "adaptorch-cli",
    REPO_ROOT / "packages" / "adaptorch-mcp",
)


def _project_metadata(pyproject_path: Path) -> dict[str, object]:
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = payload.get("project")
    assert isinstance(project, dict)
    return project


def test_canonical_license_keeps_classicmate_ownership_and_terms() -> None:
    # Given / When
    canonical = (REPO_ROOT / "LICENSE").read_bytes()
    text = canonical.decode("utf-8")
    normalized = " ".join(text.split())

    # Then
    assert hashlib.sha256(canonical).hexdigest() == CANONICAL_LICENSE_SHA256
    assert text.startswith("Copyright (c) 2026 ClassicMate. All rights reserved.")
    assert "proprietary and confidential" in normalized
    assert "expressly authorized by ClassicMate" in text


def test_repository_notice_assigns_copyright_to_classicmate() -> None:
    # Given
    notice_path = REPO_ROOT / "NOTICE"

    # When
    notice = notice_path.read_text(encoding="utf-8")

    # Then
    assert "Copyright (c) 2026 ClassicMate" in notice
    assert "All rights reserved" in notice


def test_monorepo_metadata_names_classicmate_as_owner() -> None:
    # Given / When
    project = _project_metadata(REPO_ROOT / "pyproject.toml")

    # Then
    assert project["authors"] == [{"name": "ClassicMate"}]
    assert project["license"] == "LicenseRef-Proprietary"
    assert project["license-files"] == ["LICENSE", "NOTICE"]


def test_all_python_packages_name_classicmate_as_owner() -> None:
    for package_root in PACKAGE_ROOTS:
        # Given / When
        project = _project_metadata(package_root / "pyproject.toml")

        # Then
        assert project["authors"] == [{"name": "ClassicMate"}]
        assert project["license"] == "LicenseRef-Proprietary"
        assert project["license-files"] == ["LICENSE"]
        urls = project.get("urls")
        assert isinstance(urls, dict)
        assert urls["Repository"] == PUBLIC_REPOSITORY
        assert urls["Issues"] == f"{PUBLIC_REPOSITORY}/issues"

        payload = tomllib.loads((package_root / "pyproject.toml").read_text(encoding="utf-8"))
        build_system = payload.get("build-system")
        assert isinstance(build_system, dict)
        requirements = build_system.get("requires")
        assert isinstance(requirements, list)
        assert "setuptools>=77" in requirements


def test_package_readmes_link_to_the_public_canonical_license() -> None:
    for package_root in PACKAGE_ROOTS:
        # Given / When
        readme = (package_root / "README.md").read_text(encoding="utf-8")

        # Then
        assert f"[LICENSE]({PUBLIC_LICENSE})" in readme
        assert "[LICENSE](LICENSE)" not in readme


def test_package_distributions_ship_the_canonical_license() -> None:
    # Given
    canonical = (REPO_ROOT / "LICENSE").read_bytes()

    for package_root in PACKAGE_ROOTS:
        # When
        packaged = (package_root / "LICENSE").read_bytes()

        # Then
        assert packaged == canonical
