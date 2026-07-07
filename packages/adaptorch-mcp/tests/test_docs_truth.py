from __future__ import annotations

import os
import re
from pathlib import Path

import adaptorch

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ENV_TOKEN_PATTERN = re.compile(r"\bADAPTORCH_[A-Z0-9_]+\b")
VERSION_TAG_PATTERN = re.compile(r"adaptorch-mcp-v\d+\.\d+\.\d+")

PHANTOM_ENV_VARS = frozenset(
    {
        "ADAPTORCH_ACCURACY_PROFILE",
        "ADAPTORCH_PARTIAL_CREDIT_PREFER_CONFIDENCE",
        "ADAPTORCH_JUDGE_OVERRIDE_MARGIN",
        "ADAPTORCH_VERIFICATION_CRITICAL_COMMANDS",
        "ADAPTORCH_VERIFICATION_CRITICAL_WEIGHT",
    }
)

NON_ENGINE_DOC_TOKENS = frozenset(
    {
        # Wrapper-only shell/template names that map to CLI flags.
        "ADAPTORCH_MCP_HTTP_HOST",
        "ADAPTORCH_MCP_HTTP_PORT",
        # Line-wrapped diagram fragment for ADAPTORCH_CONTROL_PLANE_TOKEN.
        "ADAPTORCH_CONTROL",
    }
)

SECRET_NAME_MARKERS = ("TOKEN", "SECRET", "API_KEY")


def _documentation_paths() -> list[Path]:
    return [
        REPO_ROOT / "README.md",
        PACKAGE_ROOT / "README.md",
        *sorted((REPO_ROOT / "docs").glob("*.md")),
        *sorted((REPO_ROOT / "examples").glob("*.env.example")),
    ]


def _env_tokens_by_path(paths: list[Path]) -> dict[Path, set[str]]:
    return {
        path: set(ENV_TOKEN_PATTERN.findall(path.read_text(encoding="utf-8")))
        for path in paths
    }


def _engine_env_tokens() -> set[str]:
    engine_file = adaptorch.__file__
    assert engine_file is not None
    engine_root = Path(os.path.dirname(engine_file))
    tokens: set[str] = set()
    for path in engine_root.rglob("*.py"):
        tokens.update(ENV_TOKEN_PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return tokens


def test_documented_adaptorch_env_vars_match_installed_engine_or_wrapper_allowlist() -> None:
    doc_tokens = _env_tokens_by_path(_documentation_paths())
    engine_tokens = _engine_env_tokens()

    documented_tokens = set().union(*doc_tokens.values())
    missing = {
        token: sorted(
            str(path.relative_to(REPO_ROOT))
            for path, tokens in doc_tokens.items()
            if token in tokens
        )
        for token in sorted(documented_tokens - engine_tokens - NON_ENGINE_DOC_TOKENS)
    }

    assert missing == {}


def test_phantom_accuracy_profile_env_vars_are_not_documented() -> None:
    doc_tokens = _env_tokens_by_path(_documentation_paths())

    occurrences = {
        token: sorted(
            str(path.relative_to(REPO_ROOT))
            for path, tokens in doc_tokens.items()
            if token in tokens
        )
        for token in sorted(PHANTOM_ENV_VARS)
        if any(token in tokens for tokens in doc_tokens.values())
    }

    assert occurrences == {}


def test_publishing_release_tag_matches_package_version() -> None:
    from adaptorch_mcp import __version__

    text = (REPO_ROOT / "docs" / "publishing.md").read_text(encoding="utf-8")
    tags = VERSION_TAG_PATTERN.findall(text)

    assert tags == [f"adaptorch-mcp-v{__version__}"]


def test_env_example_uses_placeholders_for_all_secret_values() -> None:
    secret_assignments: list[str] = []

    for path in sorted((REPO_ROOT / "examples").glob("*.env.example")):
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if not any(marker in name for marker in SECRET_NAME_MARKERS):
                continue
            secret_assignments.append(f"{path.relative_to(REPO_ROOT)}:{name}")
            assert value.startswith("<") and value.endswith(">")
            assert "://" not in value

    assert secret_assignments
