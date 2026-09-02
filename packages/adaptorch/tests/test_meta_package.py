"""The `adaptorch` distribution is a meta-package: metadata only, no code.

Releases 0.1.1/0.1.2 of this name shipped the whole private engine. From 0.2.0
the name installs the two thin clients and nothing else, and the wheel gate in
`scripts/check_public_wheels.py` is what keeps it that way.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = REPO_ROOT / "packages" / "adaptorch"
GATE = REPO_ROOT / "scripts" / "check_public_wheels.py"


def _build_wheel(outdir: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir), str(PACKAGE_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(outdir.glob("adaptorch-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def _gate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args], capture_output=True, text=True, check=False
    )


def test_meta_package_wheel_has_no_code_and_requires_only_the_thin_clients(
    tmp_path: Path,
) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        top_level = {name.split("/", 1)[0] for name in archive.namelist()}
        metadata = next(
            archive.read(n).decode("utf-8") for n in archive.namelist() if n.endswith("METADATA")
        )
    assert all(entry.endswith(".dist-info") for entry in top_level), top_level
    requires = sorted(
        line.removeprefix("Requires-Dist: ").strip()
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist: ")
    )
    assert requires == ["adaptorch-cli<0.2,>=0.1", "adaptorch-client<0.2,>=0.1"], requires
    assert "Name: adaptorch" in metadata
    assert "Version: 0.2.0" in metadata

    result = _gate("--wheel", str(wheel), "--distribution", "adaptorch")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_gate_rejects_a_wheel_that_smuggles_engine_code_or_depends_on_the_core(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "adaptorch-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("adaptorch/__init__.py", "")
        archive.writestr("adaptorch/control_plane/__init__.py", "")
        archive.writestr(
            "adaptorch-9.9.9.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: adaptorch\nVersion: 9.9.9\n"
            "Requires-Dist: adaptorch[api]>=0.1.0\n",
        )
    result = _gate("--wheel", str(bad), "--distribution", "adaptorch")
    assert result.returncode == 1
    assert "top-level module 'adaptorch'" in result.stdout
    assert "depends on the core distribution 'adaptorch'" in result.stdout
