"""No public package may silently reintroduce the private engine."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[3] / "scripts" / "check_public_wheels.py"


@pytest.mark.parametrize(
    ("distribution", "module", "requirement"),
    [
        ("adaptorch-mcp", "adaptorch_mcp/__init__.py", "adaptorch[api]>=0.1.0"),
        ("adaptorch-client", "adaptorch_client/__init__.py", "adaptorch_core>=0.1.0"),
        ("adaptorch", "adaptorch-9.9.9.data/purelib/adaptorch/engine.py", None),
    ],
)
def test_public_gate_rejects_core_dependency_or_relocated_code(
    tmp_path: Path, distribution: str, module: str, requirement: str | None
) -> None:
    wheel = tmp_path / "candidate.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(module, "")
        metadata = f"Metadata-Version: 2.4\nName: {distribution}\nVersion: 9.9.9\n"
        if requirement is not None:
            metadata += f"Requires-Dist: {requirement}\n"
        archive.writestr(f"{distribution}-9.9.9.dist-info/METADATA", metadata)

    result = subprocess.run(
        [sys.executable, str(GATE), "--wheel", str(wheel), "--distribution", distribution],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL" in result.stdout
    assert "PASS" not in result.stdout
