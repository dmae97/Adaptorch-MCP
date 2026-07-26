.PHONY: lint typecheck test check engine-local

PYTHONPATH := packages/adaptorch-mcp/src
# Path to a local AdaptOrch engine checkout used for algorithm-parity runs.
ENGINE_PATH ?= ..

# Install the local engine so parity tests validate the current algorithm
# instead of the published git revision pinned in pyproject.toml.
engine-local:
	uv pip install --python .venv --no-deps -e $(ENGINE_PATH)

lint:
	python -m ruff check packages/adaptorch-mcp

typecheck:
	PYTHONPATH=$(PYTHONPATH) python -m mypy packages/adaptorch-mcp/src

test:
	PYTHONPATH=$(PYTHONPATH) python -m pytest packages/adaptorch-mcp/tests -q

check: lint typecheck test
