#!/usr/bin/env bash
# Install one package's built wheel the way a user would and run its tests against it.
#
# Workspace dependencies (adaptorch-client, adaptorch-cli) resolve at the floor the
# wheel declares. A floor that admits an older published release lacking a behavior
# the package needs therefore fails here, which the source-tree test run cannot see.
#
#   scripts/test_installed_wheel.sh <package> --workspace-links   # CI: floor may be unreleased
#   scripts/test_installed_wheel.sh <package>                     # publish: floor must be on PyPI
set -euo pipefail

usage() { echo "usage: $0 <package> [--workspace-links]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
pkg=$1
mode=${2:-}
[ -z "$mode" ] || [ "$mode" = "--workspace-links" ] || usage

root=$(cd "$(dirname "$0")/.." && pwd)
[ -d "$root/packages/$pkg/tests" ] || { echo "no tests for $pkg" >&2; exit 2; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

uv build -q --wheel --out-dir "$work/dist" "$root/packages/$pkg"
wheel=$(ls "$work"/dist/*.whl)

links=()
if [ "$mode" = "--workspace-links" ]; then
  for sibling in adaptorch-client adaptorch-cli; do
    [ "$sibling" = "$pkg" ] || uv build -q --wheel --out-dir "$work/links" "$root/packages/$sibling"
  done
  links=(--find-links "$work/links")
fi

# Make the wheel's workspace requirements direct, so lowest-direct pins their floors.
python3 - "$wheel" "$work/metadata.txt" > "$work/floors.txt" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    metadata = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
    text = archive.read(metadata).decode()
with open(sys.argv[2], "w") as out:
    out.write(text)
for line in text.splitlines():
    if line.startswith("Requires-Dist: adaptorch-") and "extra ==" not in line:
        print(line.removeprefix("Requires-Dist: "))
PY

uv venv -q "$work/venv"
py="$work/venv/bin/python"
uv pip install -q --python "$py" --resolution lowest-direct "${links[@]}" -r "$work/floors.txt" "$wheel"
# Test-only tools: the package's dev extra when it declares one, plus pytest.
# Already-installed packages keep the versions resolved above.
if grep -qx 'Provides-Extra: dev' "$work/metadata.txt"; then
  uv pip install -q --python "$py" "${wheel}[dev]" pytest
else
  uv pip install -q --python "$py" pytest
fi
"$py" - <<'PY'
import importlib.metadata as metadata

for name in ("adaptorch-client", "adaptorch-cli", "adaptorch-mcp"):
    try:
        print(f"installed {name}=={metadata.version(name)}")
    except metadata.PackageNotFoundError:
        pass
PY

# Run the tests from a copy without any package source, so imports hit the wheel.
mkdir "$work/repo"
git -C "$root" ls-files -z --cached --others --exclude-standard \
  | (cd "$root" && tar --null -T - -cf -) | tar -xf - -C "$work/repo"
rm -rf "$work"/repo/packages/*/src
cd "$work/repo"
"$py" -m pytest "packages/$pkg/tests" -q -p no:cacheprovider \
  -o addopts= -o pythonpath=packages/adaptorch-mcp/legacy
