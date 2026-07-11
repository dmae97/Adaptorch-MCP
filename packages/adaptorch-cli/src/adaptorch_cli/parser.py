from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

_DEFAULT_API_URL = "https://adaptorch.com"
_CREDENTIAL_FLAGS = ("--token", "--api-key")


def _add_run_commands(parent: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = parent.add_parser("run", help="Manage runs")
    commands = run.add_subparsers(dest="run_command", required=True)

    submit = commands.add_parser("submit", help="Submit a run")
    submit.add_argument("--file", required=True, help="JSON request path, or - for stdin")
    submit.add_argument("--request-id", help="Idempotency key")

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
        default=os.environ.get("ADAPTORCH_API_URL", _DEFAULT_API_URL),
    )
    parser.add_argument("--output", choices=("json",), default="json")
    commands = parser.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="Inspect authentication")
    auth.add_subparsers(dest="auth_command", required=True).add_parser("status")

    config = commands.add_parser("config", help="Inspect configuration")
    config.add_subparsers(dest="config_command", required=True).add_parser("get")

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
    if any(
        argument.startswith(flag)
        for argument in inspected
        for flag in _CREDENTIAL_FLAGS
    ):
        build_parser().error("credential flags are not supported; use ADAPTORCH_API_KEY")
    return build_parser().parse_args(arguments)
