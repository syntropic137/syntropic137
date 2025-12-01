# justfile
#
# Command runner for Agentic Engineering Framework
# See https://github.com/casey/just

# Default target
default: help

# --- Help ---

# Show available commands
help:
    @just --list

# --- Development Commands ---

# Setup and run the development environment
dev:
    @echo "Setting up development environment..."
    uv sync
    docker compose -f docker/docker-compose.dev.yaml up --build -d
    @echo "Development environment ready. Run 'just cli --help' to get started."

# Stop development environment
dev-down:
    docker compose -f docker/docker-compose.dev.yaml down

# View development logs
dev-logs:
    docker compose -f docker/docker-compose.dev.yaml logs -f

# Reset development environment (removes volumes)
dev-reset:
    docker compose -f docker/docker-compose.dev.yaml down -v
    docker compose -f docker/docker-compose.dev.yaml up --build -d

# Run the CLI application
cli *args:
    uv run --package aef-cli aef {{args}}

# --- Testing & Quality Assurance ---

# Run all tests with coverage
test:
    uv run pytest

# Run tests with coverage report
test-cov:
    uv run pytest --cov=apps/aef-cli/src --cov=packages/aef-domain/src --cov=packages/aef-adapters/src --cov=packages/aef-shared/src --cov-report=term-missing --cov-fail-under=80

# Run linter
lint:
    uv run ruff check .

# Format code
format:
    uv run ruff format .

# Run type checker (strict mode)
typecheck:
    uv run mypy apps packages

# Run VSA validation (requires event-sourcing-platform submodule)
vsa-validate:
    @echo "VSA validation not yet implemented."
    # TODO: Implement VSA validation using the tool from lib/event-sourcing-platform

# Run all QA checks (lint, format, typecheck, test)
qa: lint format typecheck test
    @echo ""
    @echo "✅ All QA checks passed!"

# Run full QA with coverage
qa-full: lint format typecheck test-cov vsa-validate
    @echo ""
    @echo "✅ All QA checks passed with coverage!"

# --- Workflow Management ---

# Seed workflows from YAML files
seed-workflows:
    uv run --package aef-cli aef seed

# --- Utility Commands ---

# Generate .env.example from Settings class
gen-env:
    uv run python scripts/generate_env_example.py

# Lock dependencies
lock:
    uv lock

# Sync dependencies
sync:
    uv sync

# Clean up build artifacts, virtual environments, and Docker containers
clean:
    @echo "Cleaning up..."
    rm -rf .venv
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -exec rm {} + 2>/dev/null || true
    docker compose -f docker/docker-compose.dev.yaml down -v 2>/dev/null || true
    @echo "Cleanup complete."

# Update dependencies to latest versions
update:
    uv lock --upgrade
    uv sync

# Initialize git submodules
submodules-init:
    git submodule update --init --recursive

# Update git submodules to latest
submodules-update:
    git submodule update --remote --merge

# Add a new package to the workspace
new-package name:
    @echo "Creating package: {{name}}"
    mkdir -p packages/{{name}}/src/$(echo {{name}} | tr '-' '_')/
    mkdir -p packages/{{name}}/tests/
    echo "[project]\nname = \"{{name}}\"\nversion = \"0.1.0\"\nrequires-python = \">=3.12\"\ndependencies = []\n\n[build-system]\nrequires = [\"uv_build>=0.9.13\"]\nbuild-backend = \"uv_build\"" > packages/{{name}}/pyproject.toml
    echo "\"\"\"{{name}} package.\"\"\"" > packages/{{name}}/src/$(echo {{name}} | tr '-' '_')/__init__.py
    @echo "Package created at packages/{{name}}"
