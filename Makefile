.PHONY: lint typecheck test check engine-local engine-check

PYTHONPATH := packages/adaptorch-mcp/src:packages/adaptorch-client/src:packages/adaptorch-cli/src
# Path to a local AdaptOrch engine checkout used for algorithm-parity runs.
ENGINE_PATH ?= ../adaptorch
ENGINE_TESTS := \
	packages/adaptorch-mcp/tests/test_modelstudio_plan_flow.py \
	packages/adaptorch-mcp/tests/test_provider_credentials.py \
	packages/adaptorch-mcp/tests/test_control_plane_backend.py \
	packages/adaptorch-mcp/tests/test_json_depth_contract.py \
	packages/adaptorch-mcp/tests/test_quota_response_contract.py \
	packages/adaptorch-mcp/tests/test_sdk_engine_contract.py \
	packages/adaptorch-mcp/tests/test_connector_keepalive.py \
	packages/adaptorch-mcp/tests/mcp_test_support.py \
	packages/adaptorch-mcp/tests/test_parent_contract.py \
	packages/adaptorch-mcp/tests/test_verification_diagnostic_flow.py \
	packages/adaptorch-mcp/tests/test_engine_algorithm_parity.py \
	packages/adaptorch-mcp/tests/test_oauth_credentials.py \
	packages/adaptorch-mcp/tests/test_backend_admission_and_refusal.py \
	packages/adaptorch-mcp/tests/test_docs_truth.py \
	packages/adaptorch-mcp/tests/test_hardened_runtime.py \
	packages/adaptorch-mcp/tests/test_hardening.py \
	packages/adaptorch-mcp/tests/test_run_observation_contract.py \
	packages/adaptorch-mcp/tests/test_safe_connector_factory.py \
	packages/adaptorch-mcp/tests/test_submission_rejection_projection.py \
	packages/adaptorch-mcp/tests/test_tenant_usage_surface.py \
	packages/adaptorch-mcp/tests/test_wait_argument_admission.py
# Doctor checks that report the installed engine's vocabulary; they need engine-dev.
ENGINE_DIAGNOSTIC_TESTS := \
	packages/adaptorch-mcp/tests/test_diagnostics_and_smoke.py::test_diagnostics_reports_control_plane_for_valid_env \
	packages/adaptorch-mcp/tests/test_diagnostics_and_smoke.py::test_expected_core_tools_are_canonical \
	packages/adaptorch-mcp/tests/test_diagnostics_policy.py::test_diagnostics_reports_hardened_posture_without_token_length \
	packages/adaptorch-mcp/tests/test_diagnostics_policy.py::test_diagnostics_report_engine_algorithm_surface_parity \
	packages/adaptorch-mcp/tests/test_diagnostics_policy.py::test_diagnostics_fail_closed_when_the_engine_vocabulary_drifts \
	packages/adaptorch-mcp/tests/test_diagnostics_policy.py::test_diagnostics_report_unavailable_surface_without_calling_it_drift \
	packages/adaptorch-mcp/tests/test_diagnostics_policy.py::test_formatted_diagnostics_surface_the_parity_line \
	packages/adaptorch-mcp/tests/test_diagnostics_policy.py::test_diagnostics_full_profile_is_explicit_and_invalid_profile_fails_closed
PUBLIC_TEST_IGNORES := $(foreach path,$(ENGINE_TESTS),--ignore=$(path)) \
	$(foreach node,$(ENGINE_DIAGNOSTIC_TESTS),--deselect=$(node))

# Install the local engine so parity tests validate the current algorithm
# instead of the published git revision pinned in pyproject.toml.
engine-local:
	uv pip install --python .venv --no-deps -e $(ENGINE_PATH)

lint:
	python -m ruff check packages/adaptorch-mcp packages/adaptorch-client packages/adaptorch-cli

typecheck:
	PYTHONPATH=$(PYTHONPATH) python -m mypy

test:
	PYTHONPATH=$(PYTHONPATH) python -m pytest packages/adaptorch-mcp/tests packages/adaptorch-client/tests packages/adaptorch-cli/tests packages/adaptorch/tests -q $(PUBLIC_TEST_IGNORES)

check: lint typecheck test

engine-check: engine-local
	PYTHONPATH=$(PYTHONPATH) python -m pytest packages/adaptorch-mcp/tests packages/adaptorch-client/tests packages/adaptorch-cli/tests packages/adaptorch/tests -q
