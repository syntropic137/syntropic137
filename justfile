# justfile
#
# Command runner for Agentic Engineering Framework
# See https://github.com/casey/just

# Docker Compose shorthand variables
compose := "docker compose -f docker/docker-compose.yaml"
compose_dev := compose + " -f docker/docker-compose.dev.yaml"
compose_test := compose + " -f docker/docker-compose.test.yaml"
compose_selfhost := compose + " -f docker/docker-compose.selfhost.yaml"
compose_selfhost_cf := compose_selfhost + " -f docker/docker-compose.cloudflare.yaml"

# Platform detection
_os := `uname -s`
_arch := `uname -m`

# Default target
default: help

# --- Help ---

# Show available commands
help:
    @just --list

# --- First-Time Setup ---

# Run interactive setup wizard (git clone → running stack)
setup *args:
    @uv run python infra/scripts/setup.py {{args}}

# Check prerequisites only (no changes)
setup-check:
    @uv run python infra/scripts/setup.py --stage check_prerequisites

# Re-run a specific setup stage
setup-stage stage:
    @uv run python infra/scripts/setup.py --stage {{stage}}

# --- Development Commands ---
# Uses DRY Docker Compose: base + override files (ADR-034)

# Setup and run the FULL development environment (backend + frontend)
# Always rebuilds images to pick up code changes
dev: _workspace-check
    @echo "🚀 Starting full dev stack..."
    @echo ""
    @just _env-check
    @echo ""
    @echo "1️⃣ Syncing Python dependencies..."
    @uv sync
    @echo ""
    @echo "2️⃣ Building and starting Docker services..."
    @{{compose_dev}} up -d --build
    @echo ""
    @echo "3️⃣ Waiting for services to be healthy..."
    @sleep 5
    @echo ""
    @echo "4️⃣ Seeding workflows..."
    @just seed-workflows || echo "   ⚠️ Seed skipped (workflows may already exist)"
    @echo ""
    @echo "5️⃣ Seeding triggers..."
    @just seed-triggers || echo "   ⚠️ Seed skipped (triggers may already exist)"
    @echo ""
    @echo "6️⃣ Starting dashboard frontend..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @cd apps/syn-dashboard-ui && pnpm install --silent 2>/dev/null || true
    @cd apps/syn-dashboard-ui && pnpm run dev &
    @sleep 3
    @echo ""
    @just _smee-start
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
    @just _smee-stop
    @echo "   Stopping frontend (port 5173)..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @echo "   Stopping Docker services..."
    @{{compose_dev}} stop
    @echo "✅ Dev stack stopped (data preserved)"

# Stop and remove dev containers (preserves volumes)
dev-down:
    @echo "🛑 Shutting down dev stack..."
    @just _smee-stop
    @echo "   Stopping frontend (port 5173)..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @echo "   Removing Docker containers..."
    @{{compose_dev}} down
    @echo "✅ Dev stack shut down (volumes preserved)"

# View development logs
dev-logs:
    {{compose_dev}} logs -f

# Clean database, seed workflows, and start full dev stack (fresh start)
# Fresh start: wipe all data and restart from scratch
dev-fresh: _workspace-check
    @echo "🧹 Fresh start: wiping databases and restarting full stack..."
    @echo ""
    @just _env-check
    @echo ""
    @echo "1️⃣ Stopping any existing processes..."
    @-lsof -ti:5173 | xargs kill -9 2>/dev/null || true
    @echo ""
    @echo "2️⃣ Tearing down Docker services and volumes..."
    @{{compose_dev}} down -v --remove-orphans
    @echo ""
    @echo "3️⃣ Syncing Python dependencies..."
    @uv sync
    @echo ""
    @echo "4️⃣ Building and starting Docker services..."
    @{{compose_dev}} up -d --build
    @echo ""
    @echo "5️⃣ Waiting for services to be healthy..."
    @sleep 8
    @echo ""
    @echo "6️⃣ Running database migrations..."
    @-just feedback-migrate 2>/dev/null || echo "   Skipped: psql not installed (feedback tables created on first use)"
    @echo ""
    @echo "7️⃣ Seeding workflows..."
    @just seed-workflows
    @echo ""
    @echo "8️⃣ Seeding triggers..."
    @just seed-triggers
    @echo ""
    @echo "9️⃣ Starting dashboard frontend..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @cd apps/syn-dashboard-ui && pnpm install --silent 2>/dev/null || true
    @cd apps/syn-dashboard-ui && pnpm run dev &
    @sleep 3
    @echo ""
    @just _smee-start
    @echo ""
    @echo "✅ Fresh development environment ready!"
    @echo ""
    @echo "   🌐 Frontend:     http://localhost:5173"
    @echo "   🚀 Backend API:  http://localhost:8000"
    @echo "   📊 API Docs:     http://localhost:8000/docs"
    @echo "   💾 Database:     localhost:5432"
    @echo "   📦 Event Store:  localhost:50051"
    @echo "   🗂️  MinIO:        http://localhost:9001"
    @echo ""
    @echo "💡 All data has been wiped. Workflows have been re-seeded."

# --- Environment Validation ---

# Check .env configuration and warn about missing/broken settings
dev-doctor: _env-check
    @echo ""
    @echo "💡 Run 'just dev' to start the development stack."

# Check .env for common misconfigurations and warn loudly
_env-check:
    #!/usr/bin/env bash
    if [ -f .env ]; then set -a && source .env && set +a; fi
    # If OP_VAULT is set, resolve 1Password secrets into the environment
    # so the checks below see values that were stored in 1Password, not just .env.
    if [ -n "${OP_VAULT:-}" ]; then
        _op_exports=$(uv run python scripts/op_env_export.py 2>/dev/null) && eval "$_op_exports" || true
    fi
    WARNINGS=0
    ERRORS=0

    echo "🔍 Checking environment configuration..."
    echo ""

    # --- Critical: .env file exists ---
    if [ ! -f .env ]; then
        echo "   ❌ ERROR: .env file not found!"
        echo "            Run: cp .env.example .env"
        echo ""
        ERRORS=$((ERRORS + 1))
    fi

    # --- GitHub App ---
    # installation_id is intentionally NOT required here — installations are discovered
    # dynamically from webhook payloads (multi-org/multi-account support).
    if [ -n "${SYN_GITHUB_APP_ID:-}" ] && [ -n "${SYN_GITHUB_PRIVATE_KEY:-}" ]; then
        echo "   ✅ GitHub App configured (${SYN_GITHUB_APP_NAME:-syn-app}, installations resolved per-repo)"
    elif [ -n "${SYN_GITHUB_APP_ID:-}" ] || [ -n "${SYN_GITHUB_PRIVATE_KEY:-}" ]; then
        echo "   ❌ ERROR: GitHub App partially configured!"
        echo "            Both required: SYN_GITHUB_APP_ID, SYN_GITHUB_PRIVATE_KEY"
        echo ""
        ERRORS=$((ERRORS + 1))
    else
        echo "   ⚠️  WARNING: GitHub App not configured — agent workflows cannot push code"
        echo "               See: docs/deployment/github-app-setup.md"
        echo ""
        WARNINGS=$((WARNINGS + 1))
    fi

    # --- Webhook forwarding ---
    if [ -n "${DEV__SMEE_URL:-}" ]; then
        echo "   ✅ Webhook proxy configured (smee.io)"
    else
        echo "   ⚠️  WARNING: DEV__SMEE_URL not set — GitHub webhooks will NOT reach your local dashboard!"
        echo "               Triggers (self-healing, review-fix) will not fire."
        echo "               Fix: 1) Visit https://smee.io/new"
        echo "                    2) Add DEV__SMEE_URL=<your-url> to .env"
        echo "               (Webhook URL is auto-managed by just dev/dev-stop)"
        echo ""
        WARNINGS=$((WARNINGS + 1))
    fi

    # --- Webhook secret ---
    if [ -n "${SYN_GITHUB_WEBHOOK_SECRET:-}" ]; then
        echo "   ✅ Webhook secret configured"
    elif [ -n "${SYN_GITHUB_APP_ID:-}" ]; then
        echo "   ⚠️  WARNING: SYN_GITHUB_WEBHOOK_SECRET not set — webhook signature verification disabled"
        echo "               Anyone can send fake webhooks to your endpoint"
        echo ""
        WARNINGS=$((WARNINGS + 1))
    fi

    # --- Anthropic API key ---
    if [ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
        echo "   ✅ Agent credentials configured"
    else
        echo "   ⚠️  WARNING: No agent credentials (ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN)"
        echo "               Agent workflows will fail when trying to call Claude"
        echo ""
        WARNINGS=$((WARNINGS + 1))
    fi

    # --- Summary ---
    echo ""
    if [ $ERRORS -gt 0 ]; then
        echo "   ❌ ${ERRORS} error(s), ${WARNINGS} warning(s) — fix errors before continuing"
        exit 1
    elif [ $WARNINGS -gt 0 ]; then
        echo "   ⚠️  ${WARNINGS} warning(s) — some features may not work (see above)"
    else
        echo "   ✅ Environment looks good!"
    fi

# --- Webhook Forwarding (smee.io) ---

# Start smee webhook proxy (reads DEV__SMEE_URL from .env, no-op if unset)
_smee-start:
    #!/usr/bin/env bash
    if [ -f .env ]; then set -a && source .env && set +a; fi
    if [ -z "${DEV__SMEE_URL:-}" ]; then
        echo "   ℹ️  Webhook proxy skipped (DEV__SMEE_URL not set in .env)"
        echo "   💡 To receive GitHub webhooks locally:"
        echo "      1. Visit https://smee.io/new"
        echo "      2. Add DEV__SMEE_URL=<your-url> to .env"
        exit 0
    fi
    # Switch GitHub App webhook URL to Smee for local dev
    uv run python scripts/manage_webhook_url.py --mode dev || true
    # Kill any existing smee process
    pkill -f "smee-client.*${DEV__SMEE_URL}" 2>/dev/null || true
    echo "5️⃣  Starting webhook proxy (smee.io → localhost:8000)..."
    npx -y smee-client --url "$DEV__SMEE_URL" --target http://localhost:8000/webhooks/github --path /webhooks/github > /tmp/smee.log 2>&1 &
    echo "   🔗 Webhook proxy: $DEV__SMEE_URL → http://localhost:8000/webhooks/github"

# Stop smee webhook proxy and restore production webhook URL
_smee-stop:
    @-uv run python scripts/manage_webhook_url.py --mode prod 2>/dev/null || true
    @-pkill -f "smee-client" 2>/dev/null || true

# Start smee webhook proxy standalone (for use without full dev stack)
dev-webhooks:
    #!/usr/bin/env bash
    if [ -f .env ]; then set -a && source .env && set +a; fi
    if [ -z "${DEV__SMEE_URL:-}" ]; then
        echo "❌ DEV__SMEE_URL not set in .env"
        echo ""
        echo "To set up local webhook forwarding:"
        echo "  1. Visit https://smee.io/new to create a channel"
        echo "  2. Add DEV__SMEE_URL=<your-url> to .env"
        echo "  (Webhook URL is auto-managed by just dev/dev-stop)"
        exit 1
    fi
    echo "🔗 Starting webhook proxy..."
    echo "   Source: $DEV__SMEE_URL"
    echo "   Target: http://localhost:8000/webhooks/github"
    echo ""
    echo "   Press Ctrl+C to stop"
    echo ""
    npx -y smee-client --url "$DEV__SMEE_URL" --target http://localhost:8000/webhooks/github --path /webhooks/github

# View smee proxy logs
dev-webhooks-logs:
    @if [ -f /tmp/smee.log ]; then tail -f /tmp/smee.log; else echo "No smee logs found. Is the webhook proxy running?"; fi

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

    # Check for uncommitted changes in submodule (dirty state)
    SUBMODULE_DIRTY=""
    if [ -n "$(cd lib/agentic-primitives && git status --porcelain 2>/dev/null)" ]; then
        SUBMODULE_DIRTY="-dirty"
    fi

    # Get image's build commit from label (use jq for reliable parsing)
    IMAGE_COMMIT=$(docker inspect "$IMAGE" | jq -r '.[0].Config.Labels["agentic.commit"] // ""' 2>/dev/null || echo "")

    # Compare - rebuild if mismatch OR if submodule is dirty
    if [ -n "$SUBMODULE_DIRTY" ]; then
        echo "⚠️  Workspace submodule has uncommitted changes"
        echo "   Rebuilding to include latest agentic-primitives changes..."
        just workspace-build
    elif [ "$IMAGE_COMMIT" != "$SUBMODULE_COMMIT" ]; then
        echo "⚠️  Workspace image is stale (image: ${IMAGE_COMMIT:-none}, submodule: $SUBMODULE_COMMIT)"
        echo "   Rebuilding to include latest agentic-primitives changes..."
        just workspace-build
    fi

# Start dashboard in offline mode (no Docker, no external services)
# Seeds demo data automatically — just open http://localhost:5173
dev-offline:
    @echo "Starting AEF in offline mode (no Docker, no external services)..."
    @-lsof -ti:5173 | xargs kill 2>/dev/null || true
    @-lsof -ti:8000 | xargs kill 2>/dev/null || true
    @APP_ENVIRONMENT=offline uv run uvicorn syn_dashboard.main:app \
        --host 0.0.0.0 --port 8000 --reload &
    @sleep 3
    @cd apps/syn-dashboard-ui && pnpm run dev &
    @sleep 2
    @echo ""
    @echo "Offline dev mode ready!"
    @echo "   Frontend:  http://localhost:5173"
    @echo "   Backend:   http://localhost:8000"
    @echo "   API Docs:  http://localhost:8000/docs"
    @echo ""
    @echo "No Docker, no API keys, no smee — just code."
    @echo "Stop with: just dev-offline-stop"

# Start dashboard backend with webhook recording enabled
dev-record-webhooks:
    SYN_RECORD_WEBHOOKS=true just dashboard-backend

# Replay recorded webhooks against a running dashboard
replay-webhooks *args:
    uv run python scripts/replay_webhooks.py {{args}}

# Run the CLI application
cli *args:
    uv run --package syn-cli syn {{args}}

# Start the dashboard backend (API server)
# Loads .env for database connection and API keys
dashboard-backend:
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    uv run uvicorn syn_dashboard.main:app --host 0.0.0.0 --port 8000 --reload

# Start the dashboard frontend (Vite dev server)
dashboard-frontend:
    cd apps/syn-dashboard-ui && pnpm run dev

# Install dashboard frontend dependencies
dashboard-install:
    cd lib/ui-feedback/packages/ui-feedback-react && pnpm install
    cd apps/syn-dashboard-ui && pnpm install

# Build dashboard frontend for production
dashboard-build:
    cd apps/syn-dashboard-ui && pnpm run build

# Lint dashboard frontend
dashboard-lint:
    cd apps/syn-dashboard-ui && pnpm run lint

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
    {{compose_test}} up -d --build
    @echo "✅ Test stack running on ports 15432, 18080, 55051, 19000, 16379"

# Stop test stack
test-stack-stop:
    {{compose_test}} stop

# Stop and remove test stack (cleans everything)
test-stack-down:
    {{compose_test}} down -v

# Restart test stack (clean slate)
test-stack-restart: test-stack-down test-stack

# View test stack logs
test-stack-logs:
    {{compose_test}} logs -f

# --- Testing & Quality Assurance ---

# Run all tests
test:
    @echo "Running all tests..."
    uv run pytest

# Static checks: lint + format + typecheck + import check (fast, pre-commit)
check:
    @echo "=== Static Checks ==="
    @echo ""
    @echo "1️⃣ Import smoke test..."
    @just import-check
    @echo ""
    @echo "2️⃣ Linting..."
    @uv run ruff check .
    @echo ""
    @echo "3️⃣ Format check..."
    @uv run ruff format --check .
    @echo ""
    @echo "4️⃣ Type checking..."
    @uv run pyright
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

# Quick import smoke test - catches broken imports fast
import-check:
    @uv run python scripts/import_check.py

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

# Run tests with coverage report
test-cov:
    uv run pytest --cov=apps/syn-cli/src --cov=packages/syn-domain/src --cov=packages/syn-adapters/src --cov=packages/syn-shared/src --cov-report=term-missing --cov-fail-under=80

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

# Check formatting without changing files (same as CI)
format-check:
    uv run ruff format --check .

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
    @echo "🏗️  Generating architecture diagrams..."
    @cd lib/event-sourcing-platform/vsa/vsa-visualizer && npm run build > /dev/null 2>&1
    @node lib/event-sourcing-platform/vsa/vsa-visualizer/dist/index.js .topology/syn-manifest.json --format svg --type architecture --output docs/architecture

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

# Regenerate docs site content (OpenAPI spec + API reference MDX)
docs-site-gen:
    @echo "📄 Extracting OpenAPI spec from FastAPI..."
    uv run python scripts/extract_openapi.py
    @echo "📄 Generating API reference docs..."
    cd apps/syn-docs && pnpm run generate:openapi

# Build docs site (runs generation + next build)
docs-site-build: docs-site-gen
    cd apps/syn-docs && pnpm run build

# Start docs site dev server
docs:
    cd apps/syn-docs && pnpm run dev

# Check for test debt (xfail, skip, TODO in tests)
test-debt:
    @echo "🔍 Checking for test debt..."
    uv run python scripts/check_test_debt.py --warn-only

# Legacy command - replaced by new qa/qa-full structure (see ADR-035)
# qa: lint format typecheck test dashboard-qa test-debt vsa-validate


# Run full QA with coverage
# Legacy command - replaced by new qa-full (see ADR-035)
# qa-full-legacy: lint format typecheck test-cov dashboard-qa vsa-validate

# --- Workflow Management ---

# Generate llms.txt from API docs
generate-llms-txt:
    uv run python scripts/generate_llms_txt.py

# Seed workflows from YAML files
seed-workflows:
    uv run python scripts/seed_workflows.py

# Seed trigger presets (self-healing, review-fix)
seed-triggers:
    uv run python scripts/seed_triggers.py

# Seed all data (workflows + triggers)
seed-all: seed-workflows seed-triggers

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
    {{compose_dev}} down -v 2>/dev/null || true
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

# --- Workspace Performance Benchmarks ---

# Check available isolation backends
perf-check:
    uv run python -m syn_perf check

# Run all benchmarks
perf-all:
    @echo "=== Backend Availability ==="
    uv run python -m syn_perf check
    @echo ""
    @echo "=== Single Workspace Benchmark ==="
    uv run python -m syn_perf single --iterations 5
    @echo ""
    @echo "=== Parallel Scaling (10 concurrent) ==="
    uv run python -m syn_perf parallel --count 10
    @echo ""
    @echo "=== Throughput Test (30s) ==="
    uv run python -m syn_perf throughput --duration 30

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
    docker build -t syn-egress-proxy:latest -f docker/egress-proxy/Dockerfile docker/egress-proxy/

# Egress proxy port (use unique port to avoid conflicts)
PROXY_PORT := env_var_or_default("SYN_PROXY_PORT", "18080")

# Start the egress proxy
proxy-start:
    @docker rm -f syn-egress-proxy 2>/dev/null || true
    docker run -d --name syn-egress-proxy -p {{PROXY_PORT}}:8080 \
        -e ALLOWED_HOSTS="api.anthropic.com,github.com,api.github.com,pypi.org,files.pythonhosted.org" \
        syn-egress-proxy:latest
    @echo "✓ Egress proxy started on port {{PROXY_PORT}}"

# Test network allowlist enforcement
poc-allowlist:
    @echo "=== Network Allowlist Test ==="
    @echo "1. Starting egress proxy on port {{PROXY_PORT}}..."
    @just proxy-build >/dev/null 2>&1 || true
    @docker rm -f syn-egress-proxy 2>/dev/null || true
    @docker run -d --name syn-egress-proxy -p {{PROXY_PORT}}:8080 \
        -e ALLOWED_HOSTS="api.anthropic.com,github.com" \
        syn-egress-proxy:latest >/dev/null
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
    @docker rm -f syn-egress-proxy >/dev/null
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
        git config --global user.name "syn-bot[bot]" && \
        git config --global user.email "bot@syntropic137.com" && \
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
# INFRASTRUCTURE DEPLOYMENT (Self-Host)
# ============================================================================

# --- Self-Host Deployment ---

# Pre-flight check: platform detection and Docker availability
_selfhost-preflight:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Platform: {{_os}} / {{_arch}}"
    if [[ "{{_os}}" == "Darwin" ]]; then
        echo "  macOS detected"
        if ! docker info &>/dev/null; then
            echo "  ERROR: Docker is not running. Start Docker Desktop first."
            exit 1
        fi
        if [[ "{{_arch}}" == "arm64" ]]; then
            echo "  Apple Silicon — first event-store build may take 5-10 min"
        fi
    elif [[ "{{_os}}" == "Linux" ]]; then
        echo "  Linux detected"
        if ! docker info &>/dev/null; then
            echo "  ERROR: Docker is not running or user not in docker group"
            exit 1
        fi
    fi

# Start self-hosted AEF stack (no Cloudflare)
selfhost-up: _selfhost-preflight
    #!/usr/bin/env bash
    set -euo pipefail
    # Load 1Password service account token from macOS Keychain (vault-specific)
    if [ -f infra/.env ]; then
        eval "$(grep -E '^OP_VAULT=' infra/.env | head -1)"
    fi
    if [ -n "${OP_VAULT:-}" ] && [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
        if [ "$(uname -s)" = "Darwin" ]; then
            _TOKEN=$(security find-generic-password -a "$USER" -s "SYN_${_VK}" -w 2>/dev/null || true)
            if [ -n "$_TOKEN" ]; then
                export OP_SERVICE_ACCOUNT_TOKEN="$_TOKEN"
                echo "  1Password: loaded from Keychain (SYN_${_VK})"
            fi
        elif [ -n "${!_VK:-}" ]; then
            export OP_SERVICE_ACCOUNT_TOKEN="${!_VK}"
            echo "  1Password: loaded from ${_VK}"
        fi
    fi
    # Resolve 1Password secrets into env so Docker Compose sees them
    if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        _op_exports=$(uv run python scripts/op_env_export.py 2>/dev/null) && eval "$_op_exports" || true
    fi
    echo "🚀 Starting AEF self-host stack..."
    {{compose_selfhost}} up -d --build
    echo ""
    echo "⏳ Waiting for services to be ready..."
    uv run python infra/scripts/health_check.py --wait --timeout 180 || true
    echo ""
    just selfhost-status

# Start self-hosted AEF stack with Cloudflare Tunnel (recommended)
selfhost-up-tunnel: _selfhost-preflight
    #!/usr/bin/env bash
    set -euo pipefail
    # Load 1Password service account token from macOS Keychain (vault-specific)
    if [ -f infra/.env ]; then
        eval "$(grep -E '^OP_VAULT=' infra/.env | head -1)"
    fi
    if [ -n "${OP_VAULT:-}" ] && [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
        if [ "$(uname -s)" = "Darwin" ]; then
            _TOKEN=$(security find-generic-password -a "$USER" -s "SYN_${_VK}" -w 2>/dev/null || true)
            if [ -n "$_TOKEN" ]; then
                export OP_SERVICE_ACCOUNT_TOKEN="$_TOKEN"
                echo "  1Password: loaded from Keychain (SYN_${_VK})"
            fi
        elif [ -n "${!_VK:-}" ]; then
            export OP_SERVICE_ACCOUNT_TOKEN="${!_VK}"
            echo "  1Password: loaded from ${_VK}"
        fi
    fi
    # Resolve 1Password secrets into env so Docker Compose sees them
    if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        _op_exports=$(uv run python scripts/op_env_export.py 2>/dev/null) && eval "$_op_exports" || true
    fi
    echo "🚀 Starting AEF self-host stack with Cloudflare Tunnel..."
    {{compose_selfhost_cf}} up -d --build
    echo ""
    echo "⏳ Waiting for services to be ready..."
    uv run python infra/scripts/health_check.py --wait --timeout 180 || true
    echo ""
    just selfhost-status

# Stop self-host stack (auto-detects Cloudflare Tunnel)
selfhost-down:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Stopping AEF self-host stack..."
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}' 2>/dev/null | grep -q .; then
        echo "  (Cloudflare Tunnel detected)"
        {{compose_selfhost_cf}} down
    else
        {{compose_selfhost}} down
    fi

# View self-host logs (all services or specific service)
selfhost-logs *service:
    @{{compose_selfhost}} logs -f {{service}}

# Check self-host stack status
selfhost-status:
    @echo "📊 AEF Self-Host Status"
    @echo "======================="
    @{{compose_selfhost}} ps
    @echo ""
    @echo "🔗 Access Points:"
    @if [ -n "${SYN_DOMAIN:-}" ]; then \
        echo "   UI:  https://${SYN_DOMAIN}"; \
        echo "   API: https://api.${SYN_DOMAIN}"; \
    else \
        echo "   UI:  http://localhost:80"; \
        echo "   API: http://localhost:8000"; \
        echo "   (Set SYN_DOMAIN in .env for external access)"; \
    fi

# Check Cloudflare tunnel status
selfhost-tunnel-status:
    @echo "🚇 Cloudflare Tunnel Status"
    @echo "==========================="
    @docker logs ${COMPOSE_PROJECT_NAME:-syntropic137}-cloudflared 2>&1 | tail -20

# Restart specific self-host service
selfhost-restart service:
    @echo "Restarting {{service}}..."
    @{{compose_selfhost}} restart {{service}}

# Pull latest code, rebuild, and restart self-host (auto-detects tunnel)
selfhost-update:
    #!/usr/bin/env bash
    set -euo pipefail
    # Load 1Password service account token from macOS Keychain (vault-specific)
    if [ -f infra/.env ]; then
        eval "$(grep -E '^OP_VAULT=' infra/.env | head -1)"
    fi
    if [ -n "${OP_VAULT:-}" ] && [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
        if [ "$(uname -s)" = "Darwin" ]; then
            _TOKEN=$(security find-generic-password -a "$USER" -s "SYN_${_VK}" -w 2>/dev/null || true)
            if [ -n "$_TOKEN" ]; then
                export OP_SERVICE_ACCOUNT_TOKEN="$_TOKEN"
                echo "  1Password: loaded from Keychain (SYN_${_VK})"
            fi
        elif [ -n "${!_VK:-}" ]; then
            export OP_SERVICE_ACCOUNT_TOKEN="${!_VK}"
            echo "  1Password: loaded from ${_VK}"
        fi
    fi
    # Resolve 1Password secrets into env so Docker Compose sees them
    if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        _op_exports=$(uv run python scripts/op_env_export.py 2>/dev/null) && eval "$_op_exports" || true
    fi
    # Detect Cloudflare tunnel
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}' 2>/dev/null | grep -q .; then
        COMPOSE="{{compose_selfhost_cf}}"
        echo "  (Cloudflare Tunnel detected)"
    else
        COMPOSE="{{compose_selfhost}}"
    fi
    echo "⬆️ Updating AEF self-host..."
    echo ""
    echo "1️⃣ Pulling latest code..."
    git pull --ff-only
    echo ""
    echo "2️⃣ Syncing submodules..."
    git submodule update --init --recursive
    echo ""
    echo "3️⃣ Syncing Python dependencies..."
    uv sync
    echo ""
    echo "4️⃣ Rebuilding and restarting services..."
    $COMPOSE up -d --build
    echo ""
    echo "5️⃣ Waiting for services to be healthy..."
    uv run python infra/scripts/health_check.py --wait --timeout 180 || true
    echo ""
    just selfhost-status
    echo ""
    echo "✅ Update complete!"

# Full self-host reset (removes volumes - DATA LOSS!)
selfhost-reset:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "⚠️  WARNING: This will delete ALL data including the database!"
    echo "Press Ctrl+C within 5 seconds to cancel..."
    sleep 5
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}' 2>/dev/null | grep -q .; then
        echo "  (Cloudflare Tunnel detected)"
        {{compose_selfhost_cf}} down -v
    else
        {{compose_selfhost}} down -v
    fi
    just selfhost-up

# --- Deprecated Aliases (homelab → selfhost) ---

# DEPRECATED: use 'just selfhost-up'
homelab-up:
    @echo "DEPRECATED: use 'just selfhost-up'"
    @just selfhost-up

# DEPRECATED: use 'just selfhost-down'
homelab-down:
    @echo "DEPRECATED: use 'just selfhost-down'"
    @just selfhost-down

# DEPRECATED: use 'just selfhost-logs'
homelab-logs *service:
    @echo "DEPRECATED: use 'just selfhost-logs'"
    @just selfhost-logs {{service}}

# DEPRECATED: use 'just selfhost-status'
homelab-status:
    @echo "DEPRECATED: use 'just selfhost-status'"
    @just selfhost-status

# DEPRECATED: use 'just selfhost-tunnel-status'
homelab-tunnel-status:
    @echo "DEPRECATED: use 'just selfhost-tunnel-status'"
    @just selfhost-tunnel-status

# DEPRECATED: use 'just selfhost-restart'
homelab-restart service:
    @echo "DEPRECATED: use 'just selfhost-restart'"
    @just selfhost-restart {{service}}

# DEPRECATED: use 'just selfhost-update'
homelab-update:
    @echo "DEPRECATED: use 'just selfhost-update'"
    @just selfhost-update

# DEPRECATED: use 'just selfhost-reset'
homelab-reset:
    @echo "DEPRECATED: use 'just selfhost-reset'"
    @just selfhost-reset

# --- Local Infrastructure (No Cloudflare, uses selfhost overlay) ---

# Start infrastructure stack locally
infra-up:
    @echo "🚀 Starting AEF infrastructure stack..."
    @{{compose_selfhost}} up -d --build
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
    @{{compose_selfhost}} down

# View infrastructure logs
infra-logs *service:
    @{{compose_selfhost}} logs -f {{service}}

# Check infrastructure status
infra-status:
    @{{compose_selfhost}} ps

# --- Secrets Management ---

# Store 1Password service account token in macOS Keychain (vault-specific)
secrets-store-token:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$(uname -s)" != "Darwin" ]; then
        echo "❌ This command is macOS-only. On Linux, export the env var instead:"
        echo "   export OP_SERVICE_ACCOUNT_TOKEN_<VAULT_UPPER>=<token>"
        exit 1
    fi
    if [ -f infra/.env ]; then
        eval "$(grep -E '^OP_VAULT=' infra/.env | head -1)"
    fi
    if [ -z "${OP_VAULT:-}" ]; then
        echo "❌ OP_VAULT not set in infra/.env"
        echo "   Set it first: OP_VAULT=syn137-dev"
        exit 1
    fi
    _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
    _SVC="SYN_${_VK}"
    echo "Storing 1Password token for vault: $OP_VAULT"
    echo "Keychain entry: $_SVC"
    echo ""
    printf "Paste service account token: "
    read -rs _TOKEN
    echo ""
    if [ -z "$_TOKEN" ]; then
        echo "❌ No token provided"
        exit 1
    fi
    security add-generic-password -U -a "$USER" -s "$_SVC" -w "$_TOKEN"
    echo "✅ Token stored in Keychain as: $_SVC"
    echo "   Selfhost recipes will auto-retrieve this at startup."

# Delete 1Password token from macOS Keychain
secrets-delete-token:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$(uname -s)" != "Darwin" ]; then
        echo "❌ This command is macOS-only."
        exit 1
    fi
    if [ -f infra/.env ]; then
        eval "$(grep -E '^OP_VAULT=' infra/.env | head -1)"
    fi
    if [ -z "${OP_VAULT:-}" ]; then
        echo "❌ OP_VAULT not set in infra/.env"
        exit 1
    fi
    _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
    _SVC="SYN_${_VK}"
    security delete-generic-password -a "$USER" -s "$_SVC" 2>/dev/null \
        && echo "✅ Deleted: $_SVC" \
        || echo "⚠️  Not found: $_SVC"

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
    @echo "   just selfhost-restart dashboard"

# Verify secrets are configured
secrets-check:
    @uv run python infra/scripts/secrets_setup.py check

# Encrypt secrets with passphrase (creates .enc files safe to commit)
secrets-seal:
    @uv run python infra/scripts/secrets_setup.py seal

# Decrypt secrets from .enc files (restores plain-text for Docker)
secrets-unseal:
    @uv run python infra/scripts/secrets_setup.py unseal

# Reconfigure GitHub App (change repos, permissions, or recreate)
github-reconfigure:
    @echo "Reconfiguring GitHub App..."
    @uv run python infra/scripts/setup.py --stage configure_github_app

# Run security audit to check posture
security-audit:
    @uv run python infra/scripts/setup.py --stage security_audit

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
    @{{compose_selfhost}} build

# Build specific image
infra-build-image image:
    @echo "🔨 Building {{image}}..."
    @{{compose_selfhost}} build {{image}}
