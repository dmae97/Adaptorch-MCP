"""GitHub Action adapter for the public, remote-only AdaptOrch client."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import uuid
from pathlib import Path
from typing import NoReturn

# Use the client checked out with the action's exact Git ref, without installing
# a package or importing anything from the private engine.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/adaptorch-client/src"))

from adaptorch_client import (  # noqa: E402
    AdaptOrchAPIError,
    AdaptOrchClient,
    ClientConfig,
    PollPolicy,
    ProviderCredential,
)

MAX_INPUT_BYTES = 1024 * 1024
MAX_PROMPT_BYTES = 64 * 1024
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
RESULTS = {"OK", "DEGRADED", "FAILED"}
EVALUATIONS = {
    "PENDING", "RUNNING", "COMPLETED", "PASSED", "FAILED", "NOT_RUN", "ERROR",
    "INCONCLUSIVE", "SKIPPED",
}
VERIFICATIONS = {"PASSED", "FAILED", "NOT_RUN", "INCONCLUSIVE"}


class ActionError(Exception):
    """A fixed, user-facing message that never includes the task or credentials."""


def fail(message: str) -> NoReturn:
    raise ActionError(message)


def write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        fail("GITHUB_OUTPUT is required when running this action.")
    delimiter = f"adaptorch_{uuid.uuid4().hex}"
    with open(path, "a", encoding="utf-8") as output:
        output.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def write_summary(values: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    labels = {
        "run-id": "Run ID",
        "status": "Execution",
        "result-status": "Result",
        "evaluation-status": "Evaluation",
        "verification-status": "Verification",
    }
    with open(path, "a", encoding="utf-8") as output:
        output.write("### AdaptOrch\n\n")
        for key, label in labels.items():
            if key in values:
                output.write(f"- **{label}:** `{values[key]}`\n")
        output.write("\nExecution success is not a correctness verdict.\n")


def set_output(values: dict[str, str], name: str, value: str) -> None:
    write_output(name, value)
    values[name] = value


def number(name: str, default: str, lower: int, upper: int) -> int:
    value = os.environ.get(name, "") or default
    if not re.fullmatch(r"[0-9]{1,4}", value):
        fail(f"{name} must be an integer between {lower} and {upper}.")
    parsed = int(value)
    if not lower <= parsed <= upper:
        fail(f"{name} must be an integer between {lower} and {upper}.")
    return parsed


def workspace_path(value: str, *, new_file: bool = False) -> Path:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace or not value or Path(value).is_absolute() or "\x00" in value:
        fail("Input and report paths must be relative to GITHUB_WORKSPACE.")
    root = Path(workspace).resolve()
    try:
        path = (root / value).resolve()
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        fail("Input and report paths must stay inside GITHUB_WORKSPACE.")
    if new_file and (path.exists() or not path.parent.is_dir()):
        fail("The report path must not exist and its parent directory must exist.")
    return path


def read_input_file(name: str) -> str:
    try:
        with workspace_path(name).open("rb") as file:
            data = file.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            fail("The run specification or context file exceeds 1 MiB.")
        return data.decode("utf-8")
    except (OSError, UnicodeError):
        fail("Cannot read the run specification or context file as UTF-8.")


def make_spec(prompt: str, spec_file: str, context_file: str) -> dict:
    if context_file and not prompt.strip():
        fail("context-file can only be used together with prompt.")
    if prompt.strip():
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            fail("The prompt exceeds 64 KiB.")
        result = {
            "subtasks": [{"id": "github-action", "description": prompt}],
            "dependencies": [],
        }
        if context_file:
            result["global_context"] = read_input_file(context_file)
        return result
    try:
        # Python otherwise accepts NaN and Infinity, which are not valid JSON.
        def reject_constant(_value: str) -> NoReturn:
            fail("The run specification must contain valid JSON.")

        result = json.loads(read_input_file(spec_file), parse_constant=reject_constant)
    except (ValueError, RecursionError):
        fail("The run specification must contain valid JSON.")
    if not isinstance(result, dict) or not isinstance(result.get("subtasks"), list):
        fail("The run specification must be an object with a non-empty subtasks array.")
    if not 1 <= len(result["subtasks"]) <= 50 or not all(
        isinstance(item, dict) for item in result["subtasks"]
    ):
        fail("The run specification must contain 1 to 50 subtask objects.")
    return result


def value_or_unknown(value: str | None, allowed: set[str]) -> str:
    if value is None:
        return "NOT_REPORTED"
    return value if value in allowed else "UNKNOWN"


def valid_run_id(value: str, secrets: tuple[str, ...]) -> str:
    if not RUN_ID.fullmatch(value) or any(secret and secret in value for secret in secrets):
        fail("The run ID is invalid or unsafe to report.")
    return value


def execute(values: dict[str, str]) -> None:
    # Fail before any network call if the runner cannot retain the recovery key.
    if not os.environ.get("GITHUB_OUTPUT"):
        fail("GITHUB_OUTPUT is required when running this action.")
    token = os.environ.get("AO_API_KEY", "")
    provider = os.environ.get("AO_PROVIDER", "")
    model = os.environ.get("AO_PROVIDER_MODEL", "")
    provider_key = os.environ.get("AO_PROVIDER_KEY", "")
    prompt = os.environ.get("AO_PROMPT", "")
    spec_file = os.environ.get("AO_SPEC_FILE", "")
    context_file = os.environ.get("AO_CONTEXT_FILE", "")
    resume = os.environ.get("AO_RESUME_RUN_ID", "")
    idempotency = os.environ.get("AO_IDEMPOTENCY_KEY", "")
    report_file = os.environ.get("AO_REPORT_FILE", "")
    verification = os.environ.get("AO_VERIFICATION", "") or "report"
    if not token:
        fail("api-key is required. Store it in GitHub Actions secrets.")
    if sum(bool(value) for value in (prompt.strip(), spec_file, resume)) != 1:
        fail("Choose exactly one of prompt, run-spec-file, and resume-run-id.")
    if resume and (idempotency or context_file or provider or model or provider_key):
        fail("resume-run-id cannot be combined with submission inputs or provider credentials.")
    if any((provider, model, provider_key)) and not all((provider, model, provider_key)):
        fail("provider, provider-model, and provider-api-key must be supplied together.")
    if verification not in {"off", "report", "required"}:
        fail("verification must be off, report, or required.")
    timeout = number("AO_WAIT_TIMEOUT", "180", 1, 3600)
    interval = number("AO_POLL_INTERVAL", "2", 1, 60)
    # Validate report destination before a paid submission.
    target = workspace_path(report_file, new_file=True) if report_file else None
    secrets = (token, provider_key)
    spec = None if resume else make_spec(prompt, spec_file, context_file)
    if idempotency:
        try:
            if str(uuid.UUID(idempotency)) != idempotency.lower():
                fail("idempotency-key must be a hyphenated UUID.")
        except ValueError:
            fail("idempotency-key must be a hyphenated UUID.")
    elif not resume:
        idempotency = str(uuid.uuid4())
    if any(secret and secret == idempotency for secret in secrets):
        fail("idempotency-key must not be an API credential.")
    credential = ProviderCredential(provider, model, provider_key) if provider else None
    config = ClientConfig(os.environ.get("AO_API_URL", "") or "https://adaptorch.com", token)
    with AdaptOrchClient(config) as client:
        if resume:
            run_id = valid_run_id(resume, secrets)
        else:
            set_output(values, "idempotency-key", idempotency)
            print(f"AdaptOrch submission ID: {idempotency}", flush=True)
            assert spec is not None
            admitted = client.submit_run(spec, idempotency, provider_credential=credential)
            run_id = valid_run_id(admitted.run_id, secrets)
        set_output(values, "run-id", run_id)
        print(f"AdaptOrch run ID: {run_id}", flush=True)
        observed = client.wait_for_run(
            run_id,
            policy=PollPolicy(
                timeout_seconds=timeout,
                interval_seconds=interval,
                max_polls=math.ceil(timeout / interval) + 1,
            ),
        )
        run = observed.run
        statuses = {"QUEUED", "RUNNING", "CANCELLING", "SUCCEEDED", "FAILED", "CANCELLED"}
        status = value_or_unknown(run.status.upper() if run else None, statuses)
        set_output(values, "status", status)
        if run is not None:
            set_output(values, "result-status", value_or_unknown(run.result_status, RESULTS))
            evaluation = value_or_unknown(run.evaluation_status, EVALUATIONS)
            set_output(values, "evaluation-status", evaluation)
        if observed.reason.value != "terminal":
            fail("Run observation stopped before a terminal state; resume with the run ID.")
        if status != "SUCCEEDED":
            fail("The AdaptOrch run did not succeed. Inspect the run ID in the dashboard.")
        verdict = "NOT_REQUESTED"
        if verification != "off":
            try:
                report = client.get_evidence(run_id)
                verdict = value_or_unknown(report.verification_status, VERIFICATIONS)
            except AdaptOrchAPIError:
                verdict = "UNAVAILABLE"
        set_output(values, "verification-status", verdict)
        if target is not None:
            report = client.get_run_report(run_id, format="json")
            try:
                with target.open("xb") as output:
                    output.write(report.content)
            except OSError:
                fail("Could not create the requested report file.")
            set_output(values, "report-sha256", report.sha256)
        if verification == "required" and verdict != "PASSED":
            fail("Verification was not reported as PASSED; check the run evidence.")


def main() -> int:
    values: dict[str, str] = {}
    try:
        execute(values)
        return 0
    except ActionError as error:
        print(f"::error::{error}", file=sys.stderr)
    except AdaptOrchAPIError as error:
        status = error.status_code
        suffix = f" (HTTP {status})" if isinstance(status, int) and 100 <= status <= 599 else ""
        print(
            f"::error::AdaptOrch request or response failed{suffix}; "
            "use the same submission ID to recover.",
            file=sys.stderr,
        )
    except (OSError, ValueError, TypeError, OverflowError):
        print(
            "::error::Invalid configuration or local file error; check action inputs.",
            file=sys.stderr,
        )
    finally:
        try:
            write_summary(values)
        except OSError:
            print("::warning::Could not write the AdaptOrch job summary.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
