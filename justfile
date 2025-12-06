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

# Force start full dev stack (kills existing processes on ports 5173, 8000, 8001)
dev-force:
    @echo "Stopping any existing processes on ports 5173, 8000, 8001..."
    -lsof -ti:5173 | xargs kill -9 2>/dev/null || true
    -lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    -lsof -ti:8001 | xargs kill -9 2>/dev/null || true
    @echo "Starting Docker services..."
    docker compose -f docker/docker-compose.dev.yaml up -d
    @sleep 2
    @echo "Starting dashboard backend on :8000..."
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    uv run uvicorn aef_dashboard.main:app --host 0.0.0.0 --port 8000 --reload &
    @sleep 2
    @echo "Starting feedback API on :8001..."
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    cd lib/ui-feedback/backend/ui-feedback-api && \
    UI_FEEDBACK_DATABASE_URL=$AEF_PROJECTIONS_DATABASE_URL \
    uv run uvicorn ui_feedback.main:app --host 0.0.0.0 --port 8001 --reload &
    @sleep 2
    @echo "Starting dashboard frontend on :5173..."
    @cd apps/aef-dashboard-ui && pnpm run dev &
    @sleep 2
    @echo ""
    @echo "✅ Development stack ready!"
    @echo "   Frontend:     http://localhost:5173"
    @echo "   Backend:      http://localhost:8000"
    @echo "   Feedback API: http://localhost:8001"
    @echo "   API Docs:     http://localhost:8000/docs"

# Clean database, seed workflows, and start full dev stack (fresh start)
dev-fresh:
    @echo "🧹 Cleaning database and restarting full stack..."
    docker compose -f docker/docker-compose.dev.yaml down -v
    @echo "Building & starting Docker services (PostgreSQL + Event Store)..."
    docker compose -f docker/docker-compose.dev.yaml up -d --build
    @sleep 4
    @echo "🌱 Running database migrations..."
    just feedback-migrate
    @echo "🌱 Seeding workflows (before backend starts)..."
    just seed-workflows
    @echo ""
    @echo "Stopping any existing processes on ports 5173, 8000, 8001..."
    -lsof -ti:5173 | xargs kill -9 2>/dev/null || true
    -lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    -lsof -ti:8001 | xargs kill -9 2>/dev/null || true
    @sleep 1
    @echo "Starting dashboard backend on :8000..."
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    uv run uvicorn aef_dashboard.main:app --host 0.0.0.0 --port 8000 --reload &
    @sleep 4
    @echo "Starting feedback API on :8001..."
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    cd lib/ui-feedback/backend/ui-feedback-api && \
    UI_FEEDBACK_DATABASE_URL=$AEF_PROJECTIONS_DATABASE_URL \
    uv run uvicorn ui_feedback.main:app --host 0.0.0.0 --port 8001 --reload &
    @sleep 2
    @echo "Starting dashboard frontend on :5173..."
    @cd apps/aef-dashboard-ui && pnpm run dev &
    @sleep 2
    @echo ""
    @echo "✅ Fresh development environment ready!"
    @echo "   Frontend:     http://localhost:5173"
    @echo "   Backend:      http://localhost:8000"
    @echo "   Feedback API: http://localhost:8001"
    @echo "   API Docs:     http://localhost:8000/docs"

# Run the CLI application
cli *args:
    uv run --package aef-cli aef {{args}}

# Start the dashboard backend (API server)
# Loads .env for database connection and API keys
dashboard-backend:
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    uv run uvicorn aef_dashboard.main:app --host 0.0.0.0 --port 8000 --reload

# Start the dashboard frontend (Vite dev server)
dashboard-frontend:
    cd apps/aef-dashboard-ui && pnpm run dev

# Install dashboard frontend dependencies
dashboard-install:
    cd lib/ui-feedback/packages/ui-feedback-react && pnpm install
    cd apps/aef-dashboard-ui && pnpm install

# Build dashboard frontend for production
dashboard-build:
    cd apps/aef-dashboard-ui && pnpm run build

# Lint dashboard frontend
dashboard-lint:
    cd apps/aef-dashboard-ui && pnpm run lint

# --- UI Feedback Commands ---

# Start the feedback API server
feedback-backend:
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    cd lib/ui-feedback/backend/ui-feedback-api && \
    UI_FEEDBACK_DATABASE_URL=$AEF_PROJECTIONS_DATABASE_URL \
    uv run uvicorn ui_feedback.main:app --host 0.0.0.0 --port 8001 --reload

# Run feedback database migrations
feedback-migrate:
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    psql $AEF_PROJECTIONS_DATABASE_URL -f lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/migrations/001_feedback_tables.sql

# Install feedback widget dependencies
feedback-install:
    cd lib/ui-feedback/backend/ui-feedback-api && uv sync
    cd lib/ui-feedback/packages/ui-feedback-react && pnpm install

# Full dashboard QA (lint + build)
dashboard-qa: dashboard-lint dashboard-build
    @echo "✅ Dashboard UI checks passed!"

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

# Run all QA checks (Python + Frontend)
qa: lint format typecheck test dashboard-qa
    @echo ""
    @echo "✅ All QA checks passed!"

# Run Python-only QA (faster, no frontend build)
qa-python: lint format typecheck test
    @echo ""
    @echo "✅ Python QA checks passed!"

# Run full QA with coverage
qa-full: lint format typecheck test-cov dashboard-qa vsa-validate
    @echo ""
    @echo "✅ All QA checks passed with coverage!"

# --- Workflow Management ---

# Seed workflows from YAML files
seed-workflows:
    uv run --package aef-cli aef workflow seed

# --- Utility Commands ---

# Validate event store by querying PostgreSQL for stored events
validate-events:
    uv run python scripts/validate_event_store.py

# Generate .env.example from Settings class
gen-env:
    uv run python scripts/generate_env_example.py

# Lock dependencies
lock:
    uv lock

# Sync dependencies
sync:
    uv sync

# Sync event-sourcing platform (after local changes to lib/event-sourcing-platform)
sync-es:
    @echo "🔄 Rebuilding event-sourcing-python from local source..."
    uv sync --reinstall-package event-sourcing-python
    @echo "✅ event-sourcing-python synced!"
    @uv run python -c "from event_sourcing.client.grpc_client import GrpcEventStoreClient; print('  Methods:', len([m for m in dir(GrpcEventStoreClient) if not m.startswith('_')]), 'public methods available')"

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
