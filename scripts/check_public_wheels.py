#!/usr/bin/env python3
"""Fail when a public wheel carries engine code or depends on the private core.

The private engine left PyPI on 2026-09-02; every distribution this repository
publishes must stay thin. The rule is mechanical:

* a wheel may only contain the import package that belongs to it
  (``adaptorch-client`` -> ``adaptorch_client`` ...); the ``adaptorch``
  meta-package may contain no code at all;
* no wheel may declare a ``Requires-Dist`` on the ``adaptorch`` distribution
  (the core, or the meta-package itself).

Usage::

    python scripts/check_public_wheels.py --package adaptorch adaptorch-client adaptorch-cli
    python scripts/check_public_wheels.py --wheel dist/adaptorch-0.2.0-py3-none-any.whl \
        --distribution adaptorch

Exit ``0`` when every checked wheel passes, ``1`` on any FAIL, ``2`` when a
build or read fails. ``adaptorch-mcp`` still wraps the engine in-process until
it becomes a stdio bridge (distribution plan T4); its core dependency is
reported as WARN so the exception stays visible instead of silently allowed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DISTRIBUTION = "adaptorch"
ALLOWED_TOP_LEVEL: dict[str, frozenset[str]] = {
    "adaptorch": frozenset(),
    "adaptorch-client": frozenset({"adaptorch_client"}),
    "adaptorch-cli": frozenset({"adaptorch_cli"}),
    "adaptorch-mcp": frozenset({"adaptorch_mcp"}),
}
KNOWN_CORE_DEPENDENTS: dict[str, str] = {
    "adaptorch-mcp": "wraps the engine in-process until distribution plan T4 lands",
}
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


class GateError(Exception):
    """A wheel could not be built or read; the gate cannot give a verdict."""


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True, slots=True)
class WheelFacts:
    distribution: str
    top_level: frozenset[str]
    requires: tuple[str, ...]


def inspect_wheel(path: Path) -> WheelFacts:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise GateError(f"cannot read wheel {path}: {exc}") from exc
    with archive:
        names = archive.namelist()
        metadata_names = [
            n for n in names if n.endswith(".dist-info/METADATA") and n.count("/") == 1
        ]
        if len(metadata_names) != 1:
            raise GateError(f"{path.name} has {len(metadata_names)} METADATA files, expected 1")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
    top_level = frozenset(
        n.split("/", 1)[0]
        for n in names
        if not n.split("/", 1)[0].endswith((".dist-info", ".data"))
    )
    distribution = ""
    requires: list[str] = []
    for line in metadata.splitlines():
        if line.startswith("Name: "):
            distribution = normalize(line.removeprefix("Name: ").strip())
        elif line.startswith("Requires-Dist: "):
            requires.append(line.removeprefix("Requires-Dist: ").strip())
    return WheelFacts(distribution, top_level, tuple(requires))


def evaluate(facts: WheelFacts, distribution: str) -> tuple[list[str], list[str]]:
    """Return (failures, warnings) for one wheel."""
    failures: list[str] = []
    warnings: list[str] = []
    if facts.distribution != normalize(distribution):
        failures.append(f"wheel Name is {facts.distribution!r}, expected {distribution!r}")
    allowed = ALLOWED_TOP_LEVEL.get(normalize(distribution))
    if allowed is None:
        failures.append(f"{distribution!r} is not a known public distribution")
        allowed = frozenset()
    for module in sorted(facts.top_level - allowed):
        failures.append(f"top-level module {module!r} must not ship in {distribution}")
    for requirement in facts.requires:
        match = _REQUIREMENT_NAME.match(requirement)
        if match is None:
            failures.append(f"unparseable Requires-Dist {requirement!r}")
            continue
        if normalize(match.group(1)) == CORE_DISTRIBUTION:
            message = f"depends on the core distribution {CORE_DISTRIBUTION!r}: {requirement}"
            reason = KNOWN_CORE_DEPENDENTS.get(normalize(distribution))
            if reason is None:
                failures.append(message)
            else:
                warnings.append(f"{message} (allowed for now: {reason})")
    return failures, warnings


def build_wheel(package: str, outdir: Path) -> Path:
    package_dir = REPO_ROOT / "packages" / package
    outdir = outdir / package  # one directory per package: wheel names share prefixes
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir), str(package_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GateError(f"build failed for {package}:\n{result.stderr.strip()[-2000:]}")
    wheels = sorted(outdir.glob("*.whl"))
    if len(wheels) != 1:
        raise GateError(f"expected one wheel for {package}, found {wheels}")
    return wheels[0]


def report(distribution: str, wheel: Path) -> bool:
    failures, warnings = evaluate(inspect_wheel(wheel), distribution)
    for warning in warnings:
        print(f"WARN  {distribution}: {warning}")
    for failure in failures:
        print(f"FAIL  {distribution}: {failure}")
    if not failures:
        print(f"PASS  {distribution}: {wheel.name}")
    return not failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Public wheel gate for the AdaptOrch packages.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--package", nargs="+", help="package directory names under packages/")
    group.add_argument("--wheel", type=Path, help="inspect an already-built wheel")
    parser.add_argument("--distribution", help="distribution name for --wheel")
    args = parser.parse_args(argv)

    ok = True
    try:
        if args.wheel is not None:
            if not args.distribution:
                parser.error("--wheel requires --distribution")
            ok = report(args.distribution, args.wheel)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                for package in args.package:
                    ok = report(package, build_wheel(package, Path(tmp))) and ok
    except GateError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
