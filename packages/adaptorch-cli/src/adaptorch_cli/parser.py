from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence

_DEFAULT_API_URL = "https://adaptorch.com"
_CREDENTIAL_FLAGS = ("--token", "--api-key")
_IDEMPOTENCY_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _idempotency_key(value: str) -> str:
    if not _IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("request ID must be a hyphenated UUID")
    return value


def _add_run_commands(parent: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = parent.add_parser("run", help="Manage runs")
    commands = run.add_subparsers(dest="run_command", required=True)

    submit = commands.add_parser("submit", help="Submit a run")
    submit.add_argument("--file", required=True, help="JSON request path, or - for stdin")
    submit.add_argument("--request-id", type=_idempotency_key, help="UUID idempotency key")

    list_parser = commands.add_parser("list", help="List runs")
    list_parser.add_argument("--status")
    list_parser.add_argument("--project-id")

    get = commands.add_parser("get", help="Get a run")
    get.add_argument("run_id")

    cancel = commands.add_parser("cancel", help="Cancel a run")
    cancel.add_argument("run_id")
    cancel.add_argument("--reason")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adaptorchctl")
    parser.add_argument(
        "--api-url",
        default=None,
        help=(
            "Control-plane origin. Resolution order: this flag, "
            "ADAPTORCH_API_URL, the stored config (auth login), then "
            f"{_DEFAULT_API_URL}."
        ),
    )
    parser.add_argument("--output", choices=("json",), default="json")
    commands = parser.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="Manage authentication")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("status", help="Show the effective credential source")
    login = auth_commands.add_parser(
        "login",
        help="Store a tenant API key (reads it from the prompt or piped stdin)",
    )
    login.add_argument(
        "--api-url",
        dest="login_api_url",
        help="Control-plane origin to persist (default: current --api-url resolution)",
    )
    login.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the whoami check before saving (offline login)",
    )
    auth_commands.add_parser("logout", help="Remove the stored API key")

    config = commands.add_parser("config", help="Inspect and update configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("get", help="Show the merged configuration (secrets masked)")
    config_set = config_commands.add_parser(
        "set",
        help="Set api_url, provider.name, provider.model, or provider.api_key",
    )
    config_set.add_argument("key")
    config_set.add_argument("value", nargs="?")
    config_set.add_argument(
        "--value-stdin",
        action="store_true",
        help="Read the value from stdin (required for secrets)",
    )
    config_unset = config_commands.add_parser(
        "unset",
        help="Remove api_url, api_key, provider, or a provider.* field",
    )
    config_unset.add_argument("key")

    commands.add_parser("whoami", help="Show the authenticated identity")
    commands.add_parser("capabilities", help="Show server capabilities")
    _add_run_commands(commands)

    evidence = commands.add_parser("evidence", help="Inspect run evidence")
    show = evidence.add_subparsers(dest="evidence_command", required=True).add_parser("show")
    show.add_argument("run_id")

    artifact = commands.add_parser("artifact", help="Inspect run artifacts")
    list_artifacts = artifact.add_subparsers(dest="artifact_command", required=True).add_parser(
        "list"
    )
    list_artifacts.add_argument("run_id")
    return parser


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    arguments = list(argv) if argv is not None else None
    inspected = arguments if arguments is not None else sys.argv[1:]
    if any(argument.startswith(flag) for argument in inspected for flag in _CREDENTIAL_FLAGS):
        build_parser().error("credential flags are not supported; use ADAPTORCH_API_KEY")
    return build_parser().parse_args(arguments)
