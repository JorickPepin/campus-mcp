.PHONY: help install fmt lint test qa build inspector clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Sync deps, including dev tooling
	uv sync

fmt:  ## Format and autofix
	uv run ruff format .
	uv run ruff check --fix .

lint:  ## Format check, lint, strict type check
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy

test:  ## Run the test suite
	uv run pytest

qa: lint test  ## Everything CI runs, in one shot

build:  ## Build the wheel and sdist
	rm -rf dist
	uv build

inspector:  ## Launch the MCP Inspector against the local server
	uv run mcp dev src/campus_mcp/server.py

clean:  ## Remove build artifacts and tool caches
	rm -rf dist build .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
