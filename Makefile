.PHONY: lint typecheck test check

PYTHONPATH := packages/adaptorch-mcp/src

lint:
	python -m ruff check packages/adaptorch-mcp

typecheck:
	PYTHONPATH=$(PYTHONPATH) python -m mypy packages/adaptorch-mcp/src

test:
	PYTHONPATH=$(PYTHONPATH) python -m pytest packages/adaptorch-mcp/tests -q

check: lint typecheck test
