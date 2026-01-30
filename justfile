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
# Uses DRY Docker Compose: base + override files (ADR-034)

# Setup and run the FULL development environment (backend + frontend)
# Always rebuilds images to pick up code changes
dev: _workspace-check
    @echo "🚀 Starting full dev stack..."
    @echo ""
    @echo "1️⃣ Syncing Python dependencies..."
    @uv sync
    @echo ""
    @echo "2️⃣ Building and starting Docker services..."
    @docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml up -d --build
    @echo ""
    @echo "3️⃣ Waiting for services to be healthy..."
    @sleep 5
    @echo ""
    @echo "4️⃣ Starting dashboard frontend..."
    @cd apps/aef-dashboard-ui && pnpm install --silent 2>/dev/null || true
    @cd apps/aef-dashboard-ui && pnpm run dev &
    @sleep 3
    @echo ""
    @echo "✅ Full development stack ready!"
    @echo ""
    @echo "   🌐 Frontend:     http://localhost:5173"
    @echo "   🚀 Backend API:  http://localhost:8000"
    @echo "   📊 API Docs:     http://localhost:8000/docs"
    @echo "   💾 Database:     localhost:5432"
    @echo "   📦 Event Store:  localhost:50051"
    @echo "   🗂️  MinIO:        http://localhost:9001"
    @echo ""
    @echo "💡 Tips:"
    @echo "   • View logs:     just dev-logs"
    @echo "   • Stop stack:    just dev-stop"
    @echo "   • Fresh start:   just dev-fresh"
    @echo "   • Run CLI:       just cli --help"

# Stop development environment (preserves data)
dev-stop:
    @echo "🛑 Stopping dev stack..."
    @echo "   Stopping frontend (port 5173)..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @echo "   Stopping Docker services..."
    @docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml stop
    @echo "✅ Dev stack stopped (data preserved)"

# Stop and remove dev containers (preserves volumes)
dev-down:
    @echo "🛑 Shutting down dev stack..."
    @echo "   Stopping frontend (port 5173)..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @echo "   Removing Docker containers..."
    @docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml down
    @echo "✅ Dev stack shut down (volumes preserved)"

# View development logs
dev-logs:
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml logs -f

# Reset development environment (removes volumes - DATA LOSS!)
dev-reset:
    @echo "⚠️  This will DELETE all database data and volumes!"
    @echo "   Press Ctrl+C to cancel, or wait 5 seconds to continue..."
    @sleep 5
    @echo ""
    @echo "🔄 Resetting dev environment..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml down -v
    @just dev
    @echo "✅ Dev environment reset complete!"

# Force start full dev stack (kills existing processes on ports 5173, 8000, 8001)
# Builds workspace image if missing
dev-force: _workspace-check
    @echo "Stopping any existing processes on ports 5173, 8000, 8001..."
    -lsof -ti:5173 | xargs kill -9 2>/dev/null || true
    -lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    -lsof -ti:8001 | xargs kill -9 2>/dev/null || true
    @echo "Starting Docker services..."
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml up -d
    @sleep 2
    @echo "Starting dashboard backend on :8000..."
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    uv run uvicorn aef_dashboard.main:app --host 0.0.0.0 --port 8000 --reload &
    @sleep 2
    @echo "Starting feedback API on :8001..."
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    cd lib/ui-feedback/backend/ui-feedback-api && \
    UI_FEEDBACK_DATABASE_URL=$DATABASE_URL \
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
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml down -v
    @echo "Building & starting Docker services (PostgreSQL + Event Store)..."
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml up -d --build
    @echo "⏳ Waiting for services to be healthy..."
    @sleep 5
    @echo "🌱 Running database migrations (optional - needs psql)..."
    -just feedback-migrate 2>/dev/null || echo "   Skipped: psql not installed (feedback tables created on first use)"
    @echo "🌱 Seeding workflows..."
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
    UI_FEEDBACK_DATABASE_URL=$DATABASE_URL \
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

# --- Workspace Image (from agentic-primitives) ---

# Build the Claude workspace Docker image using agentic-primitives
# This uses the fully-tested claude-cli provider from the submodule
workspace-build:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🔨 Building workspace image from agentic-primitives..."
    cd lib/agentic-primitives && uv run scripts/build-provider.py claude-cli
    echo "✅ Image built: agentic-workspace-claude-cli:latest"

# List all workspace image versions
workspace-versions:
    @echo "📦 Workspace image versions:"
    @docker images agentic-workspace-claude-cli | head -20

# Check if workspace image exists AND matches current submodule commit
# Poka-yoke: Automatically rebuilds if agentic-primitives was updated
_workspace-check:
    #!/usr/bin/env bash
    set -euo pipefail
    IMAGE="agentic-workspace-claude-cli:latest"

    # Check if image exists
    if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
        echo "⚠️  Workspace image not found. Building..."
        just workspace-build
        exit 0
    fi

    # Get current submodule commit (short hash)
    SUBMODULE_COMMIT=$(cd lib/agentic-primitives && git rev-parse HEAD 2>/dev/null | cut -c1-12)

    # Get image's build commit from label (use jq for reliable parsing)
    IMAGE_COMMIT=$(docker inspect "$IMAGE" | jq -r '.[0].Config.Labels["agentic.commit"] // ""' 2>/dev/null || echo "")

    # Compare - rebuild if mismatch
    if [ "$IMAGE_COMMIT" != "$SUBMODULE_COMMIT" ]; then
        echo "⚠️  Workspace image is stale (image: ${IMAGE_COMMIT:-none}, submodule: $SUBMODULE_COMMIT)"
        echo "   Rebuilding to include latest agentic-primitives changes..."
        just workspace-build
    fi

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
    UI_FEEDBACK_DATABASE_URL=$DATABASE_URL \
    uv run uvicorn ui_feedback.main:app --host 0.0.0.0 --port 8001 --reload

# Run feedback database migrations
feedback-migrate:
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    psql $DATABASE_URL -f lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/migrations/001_feedback_tables.sql

# Install feedback widget dependencies
feedback-install:
    cd lib/ui-feedback/backend/ui-feedback-api && uv sync
    cd lib/ui-feedback/packages/ui-feedback-react && pnpm install

# Full dashboard QA (lint + build)
dashboard-qa: dashboard-lint dashboard-build
    @echo "✅ Dashboard UI checks passed!"

# --- Test Stack (ephemeral, different ports) ---
# See ADR-034: Test Infrastructure Architecture

# Start test stack (ephemeral, ports +10000 from dev)
test-stack:
    @echo "🧪 Starting test stack..."
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.test.yaml up -d --build
    @echo "✅ Test stack running on ports 15432, 18080, 55051, 19000, 16379"

# Stop test stack
test-stack-stop:
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.test.yaml stop

# Stop and remove test stack (cleans everything)
test-stack-down:
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.test.yaml down -v

# Restart test stack (clean slate)
test-stack-restart: test-stack-down test-stack

# View test stack logs
test-stack-logs:
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.test.yaml logs -f

# --- Testing & Quality Assurance ---

# Run all tests
test:
    @echo "Running all tests..."
    uv run pytest

# Static checks: lint + format + typecheck (fast, pre-commit)
check:
    @echo "=== Static Checks ==="
    @echo ""
    @echo "1️⃣ Linting..."
    @uv run ruff check .
    @echo ""
    @echo "2️⃣ Format check..."
    @uv run ruff format --check .
    @echo ""
    @echo "3️⃣ Type checking..."
    @uv run pyright || echo "⚠️  Type check failed (non-blocking for now)"
    @echo ""
    @echo "✅ Static checks passed!"

# Static checks with auto-fix
check-fix:
    @echo "=== Static Checks (with auto-fix) ==="
    @echo ""
    @echo "1️⃣ Auto-fixing lint issues..."
    @uv run ruff check --fix .
    @echo ""
    @echo "2️⃣ Auto-formatting..."
    @uv run ruff format .
    @echo ""
    @echo "✅ Static checks fixed!"

# Comprehensive QA: all checks (pre-commit, comprehensive)
qa: lint format typecheck test dashboard-qa test-debt vsa-validate docs-sync
    @echo ""
    @echo "✅ All QA checks passed!"

# Full QA with coverage: qa + coverage report (pre-push, CI)
qa-full: lint format typecheck test-cov dashboard-qa vsa-validate docs-sync
    @echo ""
    @echo "✅ Full QA passed with coverage!"

# Fast unit tests (parallel execution)
test-unit:
    @echo "Running unit tests (parallel)..."
    uv run pytest -m unit -n auto --tb=short

# Integration tests (uses test-stack if running, else testcontainers)
test-integration:
    @echo "🧪 Running integration tests..."
    @echo "   (Uses test-stack if running, otherwise testcontainers)"
    uv run pytest -m integration --tb=short

# Run integration tests with test-stack lifecycle (start → test → cleanup)
test-integration-full: test-stack
    @echo "🧪 Running integration tests against test stack..."
    uv run pytest -m integration --tb=short || (just test-stack-down && exit 1)
    @echo "🧹 Cleaning up test stack..."
    just test-stack-down

# E2E tests
test-e2e:
    @echo "Running E2E tests..."
    uv run pytest -m e2e --tb=short

# Fast CI check (unit tests only, with coverage)
ci-fast:
    @echo "Running fast CI tests..."
    uv run pytest -m unit -n auto --cov --tb=short

# Run tests with coverage report
test-cov:
    uv run pytest --cov=apps/aef-cli/src --cov=packages/aef-domain/src --cov=packages/aef-adapters/src --cov=packages/aef-shared/src --cov-report=term-missing --cov-fail-under=80

# Test TimescaleDB observability stack in isolation
test-timescale-isolated:
    @echo "🧪 Starting isolated TimescaleDB test..."
    docker compose -f docker/docker-compose.observability-test.yaml up -d
    @echo "⏳ Waiting for TimescaleDB to be ready..."
    @sleep 3
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner pip install -r requirements.txt
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner python test_timescale.py
    @echo "🧹 Cleaning up..."
    docker compose -f docker/docker-compose.observability-test.yaml down -v
    @echo "✅ TimescaleDB isolated test complete!"

# Test ObservabilityWriter in isolation
test-writer-isolated:
    @echo "🧪 Starting ObservabilityWriter test..."
    docker compose -f docker/docker-compose.observability-test.yaml up -d
    @echo "⏳ Waiting for TimescaleDB to be ready..."
    @sleep 3
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner pip install -r requirements.txt
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner python test_writer.py
    @echo "🧹 Cleaning up..."
    docker compose -f docker/docker-compose.observability-test.yaml down -v
    @echo "✅ ObservabilityWriter isolated test complete!"

# Test CostProjection in isolation
test-projection-isolated:
    @echo "🧪 Starting CostProjection test..."
    docker compose -f docker/docker-compose.observability-test.yaml up -d
    @echo "⏳ Waiting for TimescaleDB to be ready..."
    @sleep 3
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner pip install -r requirements.txt
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner python test_projection.py
    @echo "🧹 Cleaning up..."
    docker compose -f docker/docker-compose.observability-test.yaml down -v
    @echo "✅ CostProjection isolated test complete!"

# Test E2E observability flow in isolation
test-observability-e2e:
    @echo "🧪 Starting E2E observability test..."
    docker compose -f docker/docker-compose.observability-test.yaml up -d
    @echo "⏳ Waiting for TimescaleDB to be ready..."
    @sleep 3
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner pip install -r requirements.txt
    docker compose -f docker/docker-compose.observability-test.yaml exec test-runner python test_e2e.py
    @echo "🧹 Cleaning up..."
    docker compose -f docker/docker-compose.observability-test.yaml down -v
    @echo "✅ E2E observability test complete!"

# Run E2E container execution tests (full flow: sidecar + workspace + agent)
test-e2e-container:
    uv run python scripts/e2e_agent_in_container_test.py

# Run E2E container tests with image rebuild
test-e2e-container-build:
    uv run python scripts/e2e_agent_in_container_test.py --build

# Pre-merge validation (all checks before opening PR)
validate-pre-merge quick="":
    @if [ "{{quick}}" = "--quick" ]; then \
        uv run python scripts/pre_merge_validation.py --quick; \
    else \
        uv run python scripts/pre_merge_validation.py; \
    fi

# Pre-merge validation (quick mode - skip E2E tests)
validate-pre-merge-quick:
    uv run python scripts/pre_merge_validation.py --quick

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
    @echo "🔍 Running VSA validation..."
    vsa validate
    @echo "✅ VSA validation passed"

# Generate architecture diagram (SVG from VSA manifest)
diagram:
    @echo "🏗️  Generating architecture diagram..."
    @cd lib/event-sourcing-platform/vsa/vsa-visualizer && npm run build > /dev/null 2>&1
    @node lib/event-sourcing-platform/vsa/vsa-visualizer/dist/index.js .topology/aef-manifest.json --format svg --output docs/architecture
    @mv docs/architecture/ARCHITECTURE.svg docs/architecture/vsa-overview.svg
    @echo "✅ Diagram generated: docs/architecture/vsa-overview.svg"

# Generate auto-generated architecture documentation
docs-gen:
    @echo "🤖 Generating architecture documentation..."
    @uv run python scripts/generate-architecture-docs.py

# Regenerate ALL architecture documentation (diagram + auto-generated docs)
docs-regen: diagram docs-gen
    @echo ""
    @echo "✅ All architecture documentation regenerated!"
    @echo ""
    @echo "📊 Auto-generated:"
    @echo "   • docs/architecture/vsa-overview.svg"
    @echo "   • docs/architecture/projection-subscriptions.md"
    @echo "   • docs/architecture/event-flows/README.md"
    @echo "   • README.md (counts updated)"
    @echo ""
    @echo "📝 Manual (edit directly):"
    @echo "   • docs/architecture/event-architecture.md"
    @echo "   • docs/architecture/realtime-communication.md"
    @echo "   • docs/architecture/docker-workspace-lifecycle.md"
    @echo "   • docs/architecture/infrastructure-data-flow.md"

# Regenerate docs and fail if uncommitted changes (enforces docs are committed)
docs-sync:
    @echo "🔄 Syncing architecture documentation..."
    @uv run python scripts/generate-architecture-docs.py > /tmp/docs-gen.txt 2>&1
    @if git diff --quiet docs/architecture/projection-subscriptions.md docs/architecture/event-flows/README.md README.md 2>/dev/null; then \
        echo "✅ Architecture docs are up-to-date"; \
    else \
        echo "❌ Architecture docs need to be committed:"; \
        echo "   git add docs/architecture/ README.md && git commit -m 'docs: update generated architecture docs'"; \
        exit 1; \
    fi

# Check for test debt (xfail, skip, TODO in tests)
test-debt:
    @echo "🔍 Checking for test debt..."
    uv run python scripts/check_test_debt.py --warn-only

# Check for test debt (strict - fails on errors)
test-debt-strict:
    @echo "🔍 Checking for test debt (strict)..."
    uv run python scripts/check_test_debt.py

# Legacy command - replaced by new qa/qa-full structure (see ADR-035)
# qa: lint format typecheck test dashboard-qa test-debt vsa-validate

# Run Python-only QA (faster, no frontend build)
qa-python: lint format typecheck test test-debt vsa-validate
    @echo ""
    @echo "✅ Python QA checks passed!"

# Run full QA with coverage
# Legacy command - replaced by new qa-full (see ADR-035)
# qa-full-legacy: lint format typecheck test-cov dashboard-qa vsa-validate

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
    docker compose -f docker/docker-compose.yaml -f docker/docker-compose.dev.yaml down -v 2>/dev/null || true
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

# --- Primitives (Claude Commands/Tools/Hooks) ---

# Path to agentic-primitives CLI
_ap_cli := "lib/agentic-primitives/cli/target/release/agentic-p"

# Build agentic-primitives CLI (if needed)
primitives-cli-build:
    @echo "Building agentic-primitives CLI..."
    cd lib/agentic-primitives/cli && cargo build --release
    @echo "✅ CLI built at {{_ap_cli}}"

# Sync primitives from agentic-primitives → AEF (preserves local commands)
primitives-sync: primitives-cli-build
    @echo "🔄 Building primitives from agentic-primitives..."
    cd lib/agentic-primitives && ./cli/target/release/agentic-p build --provider claude
    @echo ""
    @echo "📦 Copying build to AEF..."
    rm -rf build/claude
    cp -r lib/agentic-primitives/build/claude build/
    @echo ""
    @echo "📥 Installing to .claude/ (local commands preserved)..."
    ./{{_ap_cli}} install --provider claude --verbose
    @echo ""
    @echo "✅ Primitives synced! Local commands in .claude/commands/ are preserved."

# Show what's managed vs local in .claude/
primitives-status:
    #!/usr/bin/env bash
    echo "📋 Primitives Status"
    echo "===================="
    echo ""
    echo "Managed (from agentic-primitives):"
    if [ -f .claude/.agentic-manifest.yaml ]; then
        grep -E "^- id:" .claude/.agentic-manifest.yaml | sed 's/- id:/  •/'
    else
        echo "  No manifest found - run 'just primitives-sync' first"
    fi
    echo ""
    echo "Local (repo-specific, not synced):"
    if [ -f .claude/.agentic-manifest.yaml ]; then
        for f in $(find .claude/commands -name "*.md" 2>/dev/null); do
            rel=${f#.claude/}
            if ! grep -q "$rel" .claude/.agentic-manifest.yaml 2>/dev/null; then
                echo "  • $rel"
            fi
        done
    else
        find .claude/commands -name "*.md" 2>/dev/null | sed 's/^/  • /'
    fi

# List local-only commands (candidates for contribution to agentic-primitives)
primitives-local:
    #!/usr/bin/env bash
    echo "📝 Local Commands (not from agentic-primitives)"
    echo "================================================"
    echo "These can be contributed back to agentic-primitives:"
    echo ""
    if [ -f .claude/.agentic-manifest.yaml ]; then
        for f in $(find .claude/commands -name "*.md" 2>/dev/null); do
            rel=${f#.claude/}
            if ! grep -q "$rel" .claude/.agentic-manifest.yaml 2>/dev/null; then
                echo "  $f"
            fi
        done
    else
        find .claude/commands -name "*.md" 2>/dev/null
    fi

# Clean primitives build artifacts
primitives-clean:
    rm -rf build/claude
    @echo "✅ Cleaned build/claude"

# --- Workspace Performance Benchmarks ---

# Check available isolation backends
perf-check:
    uv run python -m aef_perf check

# Run single workspace benchmark (5 iterations)
perf-single iterations="5":
    uv run python -m aef_perf single --iterations {{iterations}}

# Run parallel scaling benchmark
perf-parallel count="10":
    uv run python -m aef_perf parallel --count {{count}}

# Run throughput benchmark
perf-throughput duration="30":
    uv run python -m aef_perf throughput --duration {{duration}}

# Compare all available backends
perf-compare:
    uv run python -m aef_perf compare --iterations 3

# Run all benchmarks
perf-all:
    @echo "=== Backend Availability ==="
    uv run python -m aef_perf check
    @echo ""
    @echo "=== Single Workspace Benchmark ==="
    uv run python -m aef_perf single --iterations 5
    @echo ""
    @echo "=== Parallel Scaling (10 concurrent) ==="
    uv run python -m aef_perf parallel --count 10
    @echo ""
    @echo "=== Throughput Test (30s) ==="
    uv run python -m aef_perf throughput --duration 30

# Run benchmark and save JSON report
perf-report:
    @mkdir -p reports
    uv run python -m aef_perf single --iterations 10 --output reports/perf-single.json
    uv run python -m aef_perf parallel --count 10 --output reports/perf-parallel.json
    @echo "Reports saved to reports/"

# Demo workspace events E2E
demo-workspace-events:
    uv run python scripts/demo_workspace_events.py

# Run isolation POC (tests network, GitHub clone, Claude SDK)
poc-isolation mode="mock":
    uv run python scripts/poc_e2e_agent_isolation.py --{{mode}}

# Quick isolation tests (no API key needed)
poc-isolation-quick:
    @echo "=== Test 1: Network Isolation ==="
    docker run --rm --network=none python:3.12-slim sh -c "python -c \"import socket; socket.create_connection(('8.8.8.8', 53), timeout=1)\"" 2>&1 || echo "✓ Network isolation confirmed"
    @echo ""
    @echo "=== Test 2: GitHub Clone ==="
    docker run --rm --network=bridge python:3.12-slim sh -c "apt-get update -qq 2>/dev/null && apt-get install -y -qq git 2>/dev/null && git clone --depth 1 https://github.com/octocat/Hello-World.git /tmp/repo && echo '✓ GitHub clone successful'"
    @echo ""
    @echo "=== Test 3: Claude SDK Install ==="
    docker run --rm --network=bridge python:3.12-slim sh -c "pip install -q anthropic && python -c 'from anthropic import Anthropic; print(\"✓ Claude SDK installed\")'"

# --- Egress Proxy (Network Allowlist) ---

# Build the egress proxy image
proxy-build:
    docker build -t aef-egress-proxy:latest -f docker/egress-proxy/Dockerfile docker/egress-proxy/

# Egress proxy port (use unique port to avoid conflicts)
PROXY_PORT := env_var_or_default("AEF_PROXY_PORT", "18080")

# Start the egress proxy
proxy-start:
    @docker rm -f aef-egress-proxy 2>/dev/null || true
    docker run -d --name aef-egress-proxy -p {{PROXY_PORT}}:8080 \
        -e ALLOWED_HOSTS="api.anthropic.com,github.com,api.github.com,pypi.org,files.pythonhosted.org" \
        aef-egress-proxy:latest
    @echo "✓ Egress proxy started on port {{PROXY_PORT}}"

# Stop the egress proxy
proxy-stop:
    docker rm -f aef-egress-proxy
    @echo "✓ Egress proxy stopped"

# View proxy logs
proxy-logs:
    docker logs -f aef-egress-proxy

# Test network allowlist enforcement
poc-allowlist:
    @echo "=== Network Allowlist Test ==="
    @echo "1. Starting egress proxy on port {{PROXY_PORT}}..."
    @just proxy-build >/dev/null 2>&1 || true
    @docker rm -f aef-egress-proxy 2>/dev/null || true
    @docker run -d --name aef-egress-proxy -p {{PROXY_PORT}}:8080 \
        -e ALLOWED_HOSTS="api.anthropic.com,github.com" \
        aef-egress-proxy:latest >/dev/null
    @sleep 2
    @echo ""
    @echo "2. Testing ALLOWED host (github.com)..."
    @docker run --rm --add-host=host.docker.internal:host-gateway \
        -e HTTP_PROXY=http://host.docker.internal:{{PROXY_PORT}} \
        -e HTTPS_PROXY=http://host.docker.internal:{{PROXY_PORT}} \
        curlimages/curl -s -o /dev/null -w "%{http_code}" --insecure https://github.com || echo "Connection failed"
    @echo " <- Expected: 200"
    @echo ""
    @echo "3. Testing BLOCKED host (evil.com)..."
    @docker run --rm --add-host=host.docker.internal:host-gateway \
        -e HTTP_PROXY=http://host.docker.internal:{{PROXY_PORT}} \
        -e HTTPS_PROXY=http://host.docker.internal:{{PROXY_PORT}} \
        curlimages/curl -s -o /dev/null -w "%{http_code}" --insecure https://evil.com || echo "403"
    @echo " <- Expected: 403"
    @echo ""
    @docker rm -f aef-egress-proxy >/dev/null
    @echo "✓ Network allowlist test complete!"

# Test container logging setup
poc-logging:
    @echo "=== Container Logging Test ==="
    @echo "Testing: Create log dir → Write logs → Read logs"
    @echo ""
    docker run --rm python:3.12-slim sh -c '\
        mkdir -p /workspace/.logs && \
        echo "{\"timestamp\":\"2025-01-01T00:00:00Z\",\"level\":\"INFO\",\"message\":\"Agent started\",\"event_type\":\"info\"}" >> /workspace/.logs/agent.jsonl && \
        echo "{\"timestamp\":\"2025-01-01T00:00:01Z\",\"level\":\"INFO\",\"message\":\"Command: git clone\",\"event_type\":\"command\",\"exit_code\":0}" >> /workspace/.logs/agent.jsonl && \
        echo "{\"timestamp\":\"2025-01-01T00:00:02Z\",\"level\":\"ERROR\",\"message\":\"Compilation failed\",\"event_type\":\"error\"}" >> /workspace/.logs/agent.jsonl && \
        echo "Log contents:" && \
        cat /workspace/.logs/agent.jsonl && \
        echo "" && \
        echo "✓ Container logging works!"'

# Test Claude API key injection in container
poc-claude-api:
    @echo "=== Claude API Key Injection Test ==="
    @if [ -z "$ANTHROPIC_API_KEY" ]; then echo "❌ ANTHROPIC_API_KEY not set. Export it first."; exit 1; fi
    @echo "Testing: Install SDK → Call Claude API → Verify Response"
    @echo ""
    docker run --rm --network=bridge \
        -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
        python:3.12-slim sh -c '\
        pip install -q anthropic && \
        python -c "from anthropic import Anthropic; c=Anthropic(); r=c.messages.create(model=\"claude-3-5-haiku-20241022\", max_tokens=50, messages=[{\"role\":\"user\",\"content\":\"Say TEST_SUCCESS\"}]); print(r.content[0].text)" && \
        echo "" && \
        echo "✓ Claude API key injection successful!"'

# Test git identity injection in container
poc-git-identity:
    @echo "=== Git Identity Injection Test ==="
    @echo "Testing: Clone → Configure Identity → Commit → Verify Author"
    @echo ""
    docker run --rm --network=bridge python:3.12-slim sh -c '\
        apt-get update -qq 2>/dev/null && apt-get install -y -qq git 2>/dev/null && \
        git config --global user.name "aef-bot[bot]" && \
        git config --global user.email "bot@aef.dev" && \
        git clone --depth 1 https://github.com/octocat/Hello-World.git /tmp/repo && \
        cd /tmp/repo && \
        echo "# AEF Test" >> README && \
        git add README && \
        git commit -m "Test commit from AEF agent" && \
        git log -1 --format="Author: %an <%ae>" && \
        echo "" && \
        echo "✓ Git identity injection successful!"'

# --- Package Management ---

# Add a new package to the workspace
new-package name:
    @echo "Creating package: {{name}}"
    mkdir -p packages/{{name}}/src/$(echo {{name}} | tr '-' '_')/
    mkdir -p packages/{{name}}/tests/
    echo "[project]\nname = \"{{name}}\"\nversion = \"0.1.0\"\nrequires-python = \">=3.12\"\ndependencies = []\n\n[build-system]\nrequires = [\"uv_build>=0.9.13\"]\nbuild-backend = \"uv_build\"" > packages/{{name}}/pyproject.toml
    echo "\"\"\"{{name}} package.\"\"\"" > packages/{{name}}/src/$(echo {{name}} | tr '-' '_')/__init__.py
    @echo "Package created at packages/{{name}}"

# ============================================================================
# INFRASTRUCTURE DEPLOYMENT
# ============================================================================

# Infrastructure compose directory
_infra_compose := "infra/docker/compose"

# --- Homelab Deployment (with Cloudflare Tunnel) ---

# Start AEF stack with Cloudflare Tunnel (homelab)
homelab-up:
    @echo "🚀 Starting AEF homelab stack..."
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml up -d --build
    @echo ""
    @echo "⏳ Waiting for services to be ready..."
    @uv run python infra/scripts/health_check.py --wait --timeout 120 || true
    @echo ""
    @just homelab-status

# Stop homelab stack
homelab-down:
    @echo "Stopping AEF homelab stack..."
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml down

# View homelab logs (all services or specific service)
homelab-logs *service:
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml logs -f {{service}}

# Check homelab stack status
homelab-status:
    @echo "📊 AEF Homelab Status"
    @echo "===================="
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml ps
    @echo ""
    @echo "🔗 Access Points:"
    @if [ -n "${AEF_DOMAIN:-}" ]; then \
        echo "   UI:  https://${AEF_DOMAIN}"; \
        echo "   API: https://api.${AEF_DOMAIN}"; \
    else \
        echo "   UI:  http://localhost:80"; \
        echo "   API: http://localhost:8000"; \
        echo "   (Set AEF_DOMAIN in .env for external access)"; \
    fi

# Check Cloudflare tunnel status
homelab-tunnel-status:
    @echo "🚇 Cloudflare Tunnel Status"
    @echo "==========================="
    @docker logs aef-cloudflared 2>&1 | tail -20

# Restart specific homelab service
homelab-restart service:
    @echo "Restarting {{service}}..."
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml restart {{service}}

# Pull latest images and restart homelab
homelab-upgrade:
    @echo "⬆️ Upgrading AEF homelab..."
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml pull
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml up -d --build
    @echo "✅ Upgrade complete!"

# Full homelab reset (removes volumes - DATA LOSS!)
homelab-reset:
    @echo "⚠️  WARNING: This will delete ALL data including the database!"
    @echo "Press Ctrl+C within 5 seconds to cancel..."
    @sleep 5
    @cd {{_infra_compose}} && docker compose -f docker-compose.yaml -f docker-compose.homelab.yaml down -v
    @just homelab-up

# --- Local Infrastructure (No Cloudflare) ---

# Start infrastructure stack locally
infra-up:
    @echo "🚀 Starting AEF infrastructure stack..."
    @cd {{_infra_compose}} && docker compose up -d --build
    @echo ""
    @echo "⏳ Waiting for services..."
    @uv run python infra/scripts/health_check.py --wait --timeout 120 || true
    @echo ""
    @echo "✅ Infrastructure stack started!"
    @echo "   Dashboard: http://localhost:8000"
    @echo "   UI:        http://localhost:80"
    @echo "   API Docs:  http://localhost:8000/docs"

# Stop infrastructure stack
infra-down:
    @cd {{_infra_compose}} && docker compose down

# View infrastructure logs
infra-logs *service:
    @cd {{_infra_compose}} && docker compose logs -f {{service}}

# Check infrastructure status
infra-status:
    @cd {{_infra_compose}} && docker compose ps

# --- Secrets Management ---

# Generate new secrets for deployment
secrets-generate:
    @echo "🔐 Generating deployment secrets..."
    @uv run python infra/scripts/secrets_setup.py generate

# Rotate all secrets (regenerates - requires restart)
secrets-rotate:
    @echo "🔄 Rotating secrets..."
    @uv run python infra/scripts/secrets_setup.py rotate
    @echo ""
    @echo "⚠️  Restart services to apply new secrets:"
    @echo "   just homelab-restart aef-dashboard"

# Verify secrets are configured
secrets-check:
    @uv run python infra/scripts/secrets_setup.py check

# --- Health Checks ---

# Run health checks on all services
health-check:
    @uv run python infra/scripts/health_check.py

# Wait for all services to be ready
health-wait timeout="120":
    @uv run python infra/scripts/health_check.py --wait --timeout {{timeout}}

# Health check with JSON output (for CI/CD)
health-json:
    @uv run python infra/scripts/health_check.py --json

# --- Infrastructure Build ---

# Build all Docker images
infra-build:
    @echo "🔨 Building Docker images..."
    @cd {{_infra_compose}} && docker compose build

# Build specific image
infra-build-image image:
    @echo "🔨 Building {{image}}..."
    @cd {{_infra_compose}} && docker compose build {{image}}
