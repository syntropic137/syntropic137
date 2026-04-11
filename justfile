# justfile
#
# Command runner for Syntropic137
# See https://github.com/casey/just

set dotenv-load := true

# Docker Compose shorthand variables
compose := "docker compose -f docker/docker-compose.yaml"
compose_dev := compose + " -f docker/docker-compose.dev.yaml"
compose_test := compose + " -f docker/docker-compose.test.yaml"
compose_selfhost := compose + " -f docker/docker-compose.selfhost.yaml"
compose_selfhost_cf := compose_selfhost + " -f docker/docker-compose.cloudflare.yaml"
compose_dev_cf := compose_dev + " -f docker/docker-compose.dev-cloudflare.yaml"

# Platform detection
_os := `uname -s`
_arch := `uname -m`

# Default target
default: help

# --- Help ---

# Show available commands
help:
    @just --list

# --- Onboarding ---

# Self-host onboarding: use the NPX CLI — zero-clone, zero-dep, interactive wizard
# npx @syntropic137/setup init
# See https://github.com/syntropic137/syntropic137-npx for full documentation.

# Dev onboarding: submodules → .env → deps → webhook URL → GitHub App → stack
# GitHub App setup runs by default (use --skip-github to skip).
# 1Password setup is opt-in (use --1password to include).
onboard-dev *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🚀 Syntropic137 dev onboarding"
    echo ""

    # 1. Submodules
    if [ ! -d lib/agentic-primitives/.git ] || [ ! -d lib/event-sourcing-platform/.git ]; then
        echo "📦 Initializing git submodules..."
        just submodules-init
    else
        echo "✅ Submodules already initialized"
    fi

    # 3. .env
    if [ ! -f .env ]; then
        echo "📝 Creating .env from template with dev defaults..."
        cp .env.example .env
        sed -i.bak 's|^ESP_EVENT_STORE_DB_URL=.*|ESP_EVENT_STORE_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn|' .env
        sed -i.bak 's|^SYN_OBSERVABILITY_DB_URL=.*|SYN_OBSERVABILITY_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn|' .env
        rm -f .env.bak
        echo "   → .env created (edit API keys as needed)"
    else
        echo "✅ .env already exists"
    fi

    # 4. Python deps
    if [ ! -d .venv ]; then
        echo "📦 Syncing Python dependencies..."
        uv sync
    else
        echo "✅ Python dependencies already installed"
    fi

    # 5. Dashboard deps
    if [ ! -d apps/syn-dashboard-ui/node_modules ]; then
        echo "📦 Installing dashboard frontend dependencies..."
        just dashboard-install
    else
        echo "✅ Dashboard dependencies already installed"
    fi

    # 6. Kick off workspace image build in background (if needed)
    #    Runs while the user does interactive GitHub App / Cloudflare setup.
    BUILD_PID=""
    if ! docker image inspect agentic-workspace-claude-cli:latest >/dev/null 2>&1; then
        echo "🐳 Building workspace image in background..."
        just workspace-build > /tmp/syn-workspace-build.log 2>&1 &
        BUILD_PID=$!
    else
        echo "✅ Workspace image already built"
    fi

    # Source .env so subsequent checks can see existing values
    if [ -f .env ]; then set -a && source .env && set +a; fi

    # 7. Webhook delivery — Smee proxy (for dev) or Cloudflare tunnel
    # For Cloudflare tunnel setup run: npx @syntropic137/setup tunnel
    if [ -z "${DEV__SMEE_URL:-}" ]; then
        echo ""
        echo "🔗 Setting up webhook proxy (smee.io)..."
        SMEE_URL=$(uv run python -c "from infra.scripts.infra_config import create_smee_channel; print(create_smee_channel())" 2>/dev/null) || true
        if [ -n "${SMEE_URL:-}" ]; then
            echo "   ✅ Channel: $SMEE_URL"
            if grep -q '^DEV__SMEE_URL=' .env 2>/dev/null; then
                sed -i.bak "s|^DEV__SMEE_URL=.*|DEV__SMEE_URL=$SMEE_URL|" .env && rm -f .env.bak
            else
                echo "DEV__SMEE_URL=$SMEE_URL" >> .env
            fi
            export DEV__SMEE_URL="$SMEE_URL"
        else
            echo "   ⚠️  Could not auto-create smee channel (network issue?)"
            echo "   💡 Create one manually: https://smee.io/new"
            echo "      Then add DEV__SMEE_URL=<url> to .env"
        fi
    else
        echo "✅ Webhook proxy configured: ${DEV__SMEE_URL}"
    fi

    # 7. 1Password setup (opt-in with --1password)
    # The setup step below generates a script to save your secrets to a 1Password
    # vault. Prerequisites: brew install --cask 1password-cli && op signin
    if echo "{{flags}}" | grep -q -- "--1password"; then
        echo ""
        echo "🔐 1Password: generating save script..."
        echo "   See infra/docs/selfhost-deployment.md for vault setup prerequisites."
    fi

    # 7b. Resolve 1Password secrets into env (so step 8 sees them)
    eval "$(uv run python scripts/resolve_infra_env.py)"

    # 8. GitHub App setup (runs by default — skip with --skip-github)
    #    Required for agent workflows to push code.
    #    Now runs AFTER webhook URL is available.
    if echo "{{flags}}" | grep -q -- "--skip-github"; then
        echo ""
        echo "⏭️  Skipping GitHub App setup (--skip-github)"
    elif [ -n "${SYN_GITHUB_APP_ID:-}" ] && [ -n "${SYN_GITHUB_PRIVATE_KEY:-}" ]; then
        echo "✅ GitHub App already configured"
    else
        echo ""
        echo "🔑 GitHub App setup required for agent workflows to push code."
        echo "   Run the NPX setup CLI to create a GitHub App:"
        echo ""
        echo "   npx @syntropic137/setup init --skip-docker"
        echo ""
        echo "   Or use --skip-github to skip this step and configure manually later."
    fi

    # 9. Wait for workspace build if it was started
    if [ -n "$BUILD_PID" ]; then
        echo ""
        echo "⏳ Waiting for workspace image build to finish..."
        if wait "$BUILD_PID"; then
            echo "✅ Workspace image built"
        else
            echo "❌ Workspace image build failed — check /tmp/syn-workspace-build.log"
            exit 1
        fi
    fi

    # 10. 1Password summary
    echo ""
    if echo "{{flags}}" | grep -q -- "--1password"; then
        # Re-source to pick up any values written during setup + resolve 1Password
        eval "$(uv run python scripts/resolve_infra_env.py)"
        # Derive vault name
        case "${APP_ENVIRONMENT:-development}" in
            development) _VAULT="syn137-dev" ;;
            production)  _VAULT="syn137-prod" ;;
            beta)        _VAULT="syn137-beta" ;;
            staging)     _VAULT="syn137-staging" ;;
            *)           _VAULT="syn137-dev" ;;
        esac
        _ITEM="syntropic137-config"
        echo "🔐 1Password Secret Summary"
        echo "   Vault: $_VAULT  |  Item: $_ITEM"
        echo ""

        # Audit each secret: show status (in .env, missing, needs vault)
        _HAS_VALUES=""
        _MISSING=""
        for _VAR in SYN_GITHUB_APP_ID SYN_GITHUB_APP_NAME SYN_GITHUB_PRIVATE_KEY SYN_GITHUB_WEBHOOK_SECRET ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN CLOUDFLARE_TUNNEL_TOKEN SYN_PUBLIC_HOSTNAME SYN_API_PASSWORD; do
            _VAL="${!_VAR:-}"
            if [ -n "$_VAL" ]; then
                # Show redacted for secrets, full for non-secrets
                case "$_VAR" in
                    *KEY*|*SECRET*|*TOKEN*|*PASSWORD*)
                        _DISPLAY="${_VAL:0:4}****${_VAL: -4}"
                        ;;
                    *)
                        _DISPLAY="$_VAL"
                        ;;
                esac
                echo "   ✅ $_VAR=$_DISPLAY"
                _HAS_VALUES="$_HAS_VALUES $_VAR"
            else
                echo "   ⬚  $_VAR  (not set — add to vault or .env)"
                _MISSING="$_MISSING $_VAR"
            fi
        done

        echo ""

        # Show what's missing
        if [ -n "$_MISSING" ]; then
            echo "   ⚠️  Missing secrets (not required, but workflows may need them):"
            for _VAR in $_MISSING; do
                case "$_VAR" in
                    SYN_GITHUB_*)       echo "     $_VAR — needed for agent Git push" ;;
                    ANTHROPIC_API_KEY)   echo "     $_VAR — needed if not using CLAUDE_CODE_OAUTH_TOKEN" ;;
                    CLAUDE_CODE_OAUTH_TOKEN) echo "     $_VAR — needed if not using ANTHROPIC_API_KEY" ;;
                    CLOUDFLARE_TUNNEL_TOKEN) echo "     $_VAR — needed only for selfhost (just selfhost-up-tunnel)" ;;
                esac
            done
            echo ""
        fi

        # Write op command + instructions to a file (never print secrets to console)
        if [ -n "$_HAS_VALUES" ]; then
            _OP_SCRIPT=".op-save-secrets.sh"
            {
                echo "#!/usr/bin/env bash"
                echo "# Auto-generated by: just onboard-dev --1password"
                echo "# Saves your local secrets to 1Password vault: $_VAULT"
                echo "#"
                echo "# USAGE"
                echo "#   bash ${_OP_SCRIPT}"
                echo "#   rm ${_OP_SCRIPT}        # delete after — contains secrets"
                echo "#"
                echo "# PREREQUISITES"
                echo "#   1. Install: brew install --cask 1password-cli"
                echo "#   2. Sign in to the account that owns vault \"${_VAULT}\":"
                echo "#        op signin                                    # default (last used account)"
                echo "#        op signin --account my-team.1password.com    # specific account"
                echo "#"
                echo "#      The --account flag takes your sign-in address (the domain"
                echo "#      shown in 1Password app > Settings > Accounts, e.g."
                echo "#      \"my-team.1password.com\" or \"my.1password.com\" for personal)."
                echo "#"
                echo "#      Multiple accounts? op uses whichever you last signed into."
                echo "#      To check or switch:"
                echo "#        op account list                               # see all accounts + sign-in addresses"
                echo "#        op signin --account my-team.1password.com     # switch to a specific one"
                echo "#      Or pin one: export OP_ACCOUNT=my-team.1password.com"
                echo "#"
                echo "#   3. The vault \"${_VAULT}\" must exist. Create it in the"
                echo "#      1Password app or: op vault create \"${_VAULT}\""
                echo "#"
                echo "# The script automatically clears secret values from .env after saving."
                echo "# Non-secret config (APP_ID, APP_NAME) and OP_SERVICE_ACCOUNT_TOKEN are kept."
                echo "# On next startup, 1Password auto-injects the cleared secrets."
                echo "# New machine? just onboard-dev --1password picks everything up."
                echo ""
                echo "set -euo pipefail"
                echo ""
                echo "echo '🔐 Saving secrets to 1Password vault: ${_VAULT}'"
                echo "echo '   Item: ${_ITEM}'"
                echo "echo ''"
                echo ""
                echo "# Try edit first; if item doesn't exist, create it"
                echo -n "op item edit \"$_ITEM\" --vault \"$_VAULT\""
                for _VAR in SYN_GITHUB_APP_ID SYN_GITHUB_APP_NAME SYN_GITHUB_PRIVATE_KEY SYN_GITHUB_WEBHOOK_SECRET ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN CLOUDFLARE_TUNNEL_TOKEN SYN_PUBLIC_HOSTNAME SYN_API_PASSWORD; do
                    _VAL="${!_VAR:-}"
                    if [ -n "$_VAL" ]; then
                        echo " \\"
                        echo -n "  '${_VAR}=${_VAL}'"
                    fi
                done
                echo " 2>/dev/null \\"
                echo "|| op item create --category=login --title=\"$_ITEM\" --vault=\"$_VAULT\" \\"
                _FIRST=true
                for _VAR in SYN_GITHUB_APP_ID SYN_GITHUB_APP_NAME SYN_GITHUB_PRIVATE_KEY SYN_GITHUB_WEBHOOK_SECRET ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN CLOUDFLARE_TUNNEL_TOKEN SYN_PUBLIC_HOSTNAME SYN_API_PASSWORD; do
                    _VAL="${!_VAR:-}"
                    if [ -n "$_VAL" ]; then
                        if [ "$_FIRST" = true ]; then _FIRST=false; else echo " \\"; fi
                        echo -n "  '${_VAR}=${_VAL}'"
                    fi
                done
                echo ""
                echo ""
                echo "echo ''"
                echo "echo '✅ Secrets saved to 1Password.'"
                echo ""
                echo "# --- Clean secret values from .env files (keep keys with empty values) ---"
                echo "echo '🧹 Cleaning secret values from .env files...'"
                echo "_ROOT_SECRETS=(SYN_GITHUB_PRIVATE_KEY SYN_GITHUB_WEBHOOK_SECRET ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN)"
                echo "for _KEY in \"\${_ROOT_SECRETS[@]}\"; do"
                echo "  if grep -q \"^\${_KEY}=\" .env 2>/dev/null; then"
                echo "    sed -i.bak \"s|^\${_KEY}=.*|# \${_KEY}= # managed by 1Password|\" .env && rm -f .env.bak"
                echo "    echo \"   cleared: \${_KEY} (.env)\""
                echo "  fi"
                echo "done"
                echo "_INFRA_SECRETS=(CLOUDFLARE_TUNNEL_TOKEN)"
                echo "for _KEY in \"\${_INFRA_SECRETS[@]}\"; do"
                echo "  if grep -q \"^\${_KEY}=\" infra/.env 2>/dev/null; then"
                echo "    sed -i.bak \"s|^\${_KEY}=.*|# \${_KEY}= # managed by 1Password|\" infra/.env && rm -f infra/.env.bak"
                echo "    echo \"   cleared: \${_KEY} (infra/.env)\""
                echo "  fi"
                echo "done"
                echo "echo ''"
                echo "echo '   Non-secret config (APP_ID, APP_NAME) left intact.'"
                echo "echo '   OP_SERVICE_ACCOUNT_TOKEN_* left intact (resolver needs it).'"
                echo "echo '   On next startup, 1Password auto-injects the cleared secrets.'"
                echo "echo ''"
                echo "echo '🗑️  Now delete this script: rm ${_OP_SCRIPT}'"
            } > "$_OP_SCRIPT"
            chmod 600 "$_OP_SCRIPT"
            echo "   📄 1Password save script: ${_OP_SCRIPT}"
            echo "      Prerequisites + next steps are inside the script."
            echo "      Run:  bash ${_OP_SCRIPT}"
            echo "      Then: rm ${_OP_SCRIPT}"
            echo ""
            echo "   ⚠️  ${_OP_SCRIPT} contains secret values — do NOT commit it."
            echo ""
        fi
    else
        echo "💡 Optional: Store secrets in 1Password for portable setup"
        echo "   Your .env has API keys and GitHub App credentials that only"
        echo "   exist on this machine. To make setup turnkey on any machine:"
        echo ""
        echo "   1. Create a 1Password vault: syn137-dev"
        echo "   2. Create a service account with access to that vault"
        echo "   3. Run: just onboard-dev --1password"
        echo ""
        echo "   Then on any new machine: just onboard-dev --1password picks them up."
        echo "   Skip this if you don't use 1Password — everything works without it."
    fi
    echo ""

    # 11. Start dev stack
    echo ""
    echo "🚀 Starting dev stack..."
    just dev

# --- Development ---
# Uses DRY Docker Compose: base + override files (ADR-034)

# One-time contributor setup: point git at tracked hooks (core.hooksPath).
# Opt-in by design — auto-running hooks on clone is an arbitrary code execution
# risk (same reason CI uses --ignore-scripts). Run once after cloning.
install-hooks:
    git config core.hooksPath scripts/hooks
    chmod +x scripts/hooks/*
    @echo "✅ Git hooks enabled (core.hooksPath=scripts/hooks)"

# Setup and run the FULL development environment (backend + frontend)
# Always rebuilds images to pick up code changes
dev: _workspace-check
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🚀 Starting full dev stack..."
    echo ""
    just _env-check
    echo ""

    # Resolve .env + 1Password so Docker Compose inherits secrets
    eval "$(uv run python scripts/resolve_infra_env.py)"

    echo "1️⃣ Syncing Python dependencies..."
    uv sync
    echo ""

    # Auto-detect Cloudflare tunnel
    _COMPOSE=$(just _dev-compose-cmd)
    if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
        echo "   🔒 Cloudflare tunnel detected — cloudflared will start automatically"
    fi

    echo "2️⃣ Building and starting Docker services..."
    ${_COMPOSE} up -d --build
    echo ""
    echo "3️⃣ Waiting for services to be healthy..."
    sleep 5
    echo ""
    echo "5️⃣ Seeding workflows..."
    just seed-workflows || echo "   ⚠️ Seed skipped (workflows may already exist)"
    echo ""
    echo "6️⃣ Seeding triggers..."
    just seed-triggers || echo "   ⚠️ Seed skipped (triggers may already exist)"
    echo ""
    echo "6½ Seeding organization..."
    just seed-organization || echo "   ⚠️ Seed skipped (organization may already exist)"
    echo ""
    echo "7️⃣ Starting dashboard frontend..."
    lsof -ti:5173 | xargs kill 2>/dev/null || true
    sleep 1  # let previous process fully exit
    (cd apps/syn-dashboard-ui && pnpm install --silent 2>/dev/null || true)
    (cd apps/syn-dashboard-ui && pnpm run dev > /tmp/syn-dashboard.log 2>&1 &)
    sleep 3
    echo ""
    just _webhook-start
    echo ""
    echo "✅ Full development stack ready!"
    echo ""
    echo "   🌐 Dashboard:    http://localhost:5173"
    echo "   🚀 Backend API:  http://localhost:9137"
    echo "   📊 API Docs:     http://localhost:9137/docs"
    echo "   💾 Database:     localhost:5432"
    echo "   📦 Event Store:  localhost:50051"
    echo "   🗂️  MinIO:        http://localhost:9001"
    echo ""
    echo "💡 Tips:"
    echo "   • View logs:     just dev-logs"
    echo "   • Stop stack:    just dev-stop"
    echo "   • Fresh start:   just dev-fresh"
    echo "   • Run CLI:       just cli --help"

# Clean database, seed workflows, and start full dev stack (fresh start)
# Fresh start: wipe all data and restart from scratch
dev-fresh: _workspace-check
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🧹 Fresh start: wiping databases and restarting full stack..."
    echo ""
    just _env-check
    echo ""

    # Resolve .env + 1Password so Docker Compose inherits secrets
    eval "$(uv run python scripts/resolve_infra_env.py)"

    echo "1️⃣ Stopping any existing processes..."
    lsof -ti:5173 | xargs kill -9 2>/dev/null || true
    lsof -ti:5174 | xargs kill -9 2>/dev/null || true
    echo ""
    echo "2️⃣ Tearing down Docker services and volumes..."
    {{compose_dev}} down -v --remove-orphans
    echo ""
    echo "3️⃣ Syncing Python dependencies..."
    uv sync
    echo ""

    # Auto-detect Cloudflare tunnel
    _COMPOSE=$(just _dev-compose-cmd)
    if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
        echo "   🔒 Cloudflare tunnel detected — cloudflared will start automatically"
    fi

    echo "4️⃣ Building and starting Docker services..."
    ${_COMPOSE} up -d --build
    echo ""
    echo "5️⃣ Waiting for services to be healthy..."
    sleep 8
    echo ""
    echo "7️⃣ Running database migrations..."
    just feedback-migrate 2>/dev/null || echo "   Skipped: psql not installed (feedback tables created on first use)"
    echo ""
    echo "8️⃣ Seeding workflows..."
    just seed-workflows
    echo ""
    echo "9️⃣ Seeding triggers..."
    just seed-triggers
    echo ""
    echo "9½ Seeding organization..."
    just seed-organization
    echo ""
    echo "🔟 Starting dashboard frontend..."
    lsof -ti:5173 | xargs kill 2>/dev/null || true
    sleep 1
    (cd apps/syn-dashboard-ui && pnpm install --silent 2>/dev/null || true)
    (cd apps/syn-dashboard-ui && pnpm run dev > /tmp/syn-dashboard.log 2>&1 &)
    sleep 3
    echo ""
    just _webhook-start
    echo ""
    echo "✅ Fresh development environment ready!"
    echo ""
    echo "   🌐 Dashboard:    http://localhost:5173"
    echo "   🚀 Backend API:  http://localhost:9137"
    echo "   📊 API Docs:     http://localhost:9137/docs"
    echo "   💾 Database:     localhost:5432"
    echo "   📦 Event Store:  localhost:50051"
    echo "   🗂️  MinIO:        http://localhost:9001"
    echo ""
    echo "💡 All data has been wiped. Workflows have been re-seeded."

# Stop development environment (preserves data)
dev-stop:
    #!/usr/bin/env bash
    echo "🛑 Stopping dev stack..."
    just _webhook-stop
    echo "   Stopping frontends (ports 5173, 5174)..."
    lsof -ti:5173 | xargs kill 2>/dev/null || true
    lsof -ti:5174 | xargs kill 2>/dev/null || true
    echo "   Stopping Docker services..."
    $(just _dev-compose-cmd) stop
    echo "✅ Dev stack stopped (data preserved)"

# Stop and remove dev containers (preserves volumes)
dev-down:
    #!/usr/bin/env bash
    echo "🛑 Shutting down dev stack..."
    just _webhook-stop
    echo "   Stopping frontends (ports 5173, 5174)..."
    lsof -ti:5173 | xargs kill 2>/dev/null || true
    lsof -ti:5174 | xargs kill 2>/dev/null || true
    echo "   Removing Docker containers..."
    $(just _dev-compose-cmd) down
    echo "✅ Dev stack shut down (volumes preserved)"

# View development logs
dev-logs:
    {{compose_dev}} logs -f

# Check .env configuration and warn about missing/broken settings
dev-doctor: _env-check
    @echo ""
    @echo "💡 Run 'just dev' to start the development stack."

# --- CLI Node ---

# Build the Node.js CLI
cli-node-build:
    cd apps/syn-cli-node && pnpm run build


# Run CLI Node tests
cli-node-test:
    cd apps/syn-cli-node && pnpm run test

# Typecheck CLI Node
cli-node-typecheck:
    cd apps/syn-cli-node && pnpm run typecheck

# Full CLI Node QA (typecheck + test + build)
cli-node-qa: cli-node-typecheck cli-node-test cli-node-build
    @echo "CLI Node checks passed!"

# Start the API backend server
# Loads .env for database connection and API keys
api-backend:
    @if [ -f .env ]; then set -a && . ./.env && set +a; fi && \
    uv run uvicorn syn_api.main:app --host 0.0.0.0 --port 8000 --reload

# --- Dashboard & Frontend ---

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

# Full dashboard QA (lint + build)
dashboard-qa: dashboard-lint dashboard-build
    @echo "✅ Dashboard UI checks passed!"

# --- Pulse UI ---

# --- Feedback ---

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

# --- Webhooks ---

# Start smee webhook proxy standalone (DEVELOPMENT ONLY — not for production)
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
    echo "   Target: http://localhost:9137/webhooks/github"
    echo ""
    echo "   Press Ctrl+C to stop"
    echo ""
    npx -y smee-client --url "$DEV__SMEE_URL" --target http://localhost:9137/webhooks/github --path /webhooks/github

# View smee proxy logs
dev-webhooks-logs:
    @if [ -f /tmp/smee.log ]; then tail -f /tmp/smee.log; else echo "No smee logs found. Is the webhook proxy running?"; fi

# Start API backend with webhook recording enabled
dev-record-webhooks:
    SYN_RECORD_WEBHOOKS=true just api-backend

# Replay recorded webhooks against a running dashboard
replay-webhooks *args:
    uv run python scripts/replay_webhooks.py {{args}}

# --- Workspace ---

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

# --- Testing ---

# Run all tests
test:
    @echo "Running all tests..."
    uv run pytest

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
    uv run pytest --cov=packages/syn-domain/src --cov=packages/syn-adapters/src --cov=packages/syn-shared/src --cov-report=term-missing --cov-fail-under=80

# Run E2E container execution tests (full flow: sidecar + workspace + agent)
test-e2e-container:
    uv run python scripts/e2e_agent_in_container_test.py

# Run E2E container tests with image rebuild
test-e2e-container-build:
    uv run python scripts/e2e_agent_in_container_test.py --build

# Quick E2E smoke test: validate the full dev stack is working (#516)
# Starts the dev stack if not running, hits health endpoint, runs core CLI commands.
e2e-smoke:
    #!/usr/bin/env bash
    set -euo pipefail

    API_URL="http://localhost:9137"

    # 1. Check if the dev stack is already running; start it if not
    if ! curl -sf "${API_URL}/health" > /dev/null 2>&1; then
        echo "🔧 Dev stack not running — starting it..."
        just dev
        echo ""
    fi

    # 2. Wait briefly for services to stabilise
    echo "⏳ Waiting for services..."
    for i in $(seq 1 30); do
        if curl -sf "${API_URL}/health" > /dev/null 2>&1; then
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "❌ Health endpoint did not respond within 30 seconds"
            exit 1
        fi
        sleep 1
    done

    # 3. Health endpoint
    echo "🏥 Checking health endpoint..."
    curl -sf "${API_URL}/health" | python3 -m json.tool
    echo ""

    # 4. Core CLI smoke tests
    echo "🔍 Running CLI smoke tests..."
    echo ""

    echo "  → syn workflow list"
    just cli workflow list
    echo ""

    echo "  → syn session list"
    just cli session list
    echo ""

    echo "  → syn events recent --limit 5"
    just cli events recent --limit 5
    echo ""

    echo "  → syn org list"
    just cli org list
    echo ""

    echo "  → syn status"
    just cli status
    echo ""

    # 5. Success
    echo "✅ E2E smoke test passed — full stack is operational"

# Check for test debt (xfail, skip, TODO in tests)
test-debt:
    @echo "🔍 Checking for test debt..."
    uv run python scripts/check_test_debt.py --warn-only

# --- Test Stack ---
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

# --- Quality Assurance ---

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
    @echo "5️⃣ Architectural fitness..."
    @just fitness
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

# Wire up git hooks from .githooks/ — run once after cloning or when hooks change
setup-hooks:
    git config core.hooksPath .githooks
    @echo "✓ Git hooks configured (.githooks/pre-push active)"

# Comprehensive QA: all checks (pre-commit, comprehensive)
qa: lint format typecheck validate-domain-events fitness test dashboard-qa test-debt vsa-validate docs-sync
    @echo ""
    @echo "✅ All QA checks passed!"

# Full QA with coverage: qa + coverage report (pre-push, CI)
qa-full: lint format typecheck validate-domain-events fitness test-cov dashboard-qa test-debt vsa-validate docs-sync
    @echo ""
    @echo "✅ Full QA passed with coverage!"

# Run linter
lint:
    uv run ruff check .

# Format code
format:
    uv run ruff format .

# Check formatting without changing files (same as CI)
format-check:
    uv run ruff format --check .

# Ratchet: no untyped dicts in API types (dict[str, Any] or dict[str, object] in Pydantic models)
check-untyped-dicts:
    #!/usr/bin/env python3
    import re, sys
    from pathlib import Path
    threshold = int(Path(".ratchets/untyped-dicts").read_text().strip() or 0)
    text = Path("apps/syn-api/src/syn_api/types.py").read_text()
    count = len(re.findall(r"dict\[str, (?:Any|object)\]", text))
    if count > threshold:
        print(f"❌ Untyped dict ratchet exceeded: {count} occurrences (threshold: {threshold})")
        print("   Fix dict[str, Any] and dict[str, object] in apps/syn-api/src/syn_api/types.py")
        sys.exit(1)
    print(f"✓ Untyped dict check: {count}/{threshold}")

# Run type checker (strict mode)
typecheck:
    uv run pyright

# Validate domain event definitions
validate-domain-events:
    uv run python scripts/validate_domain_events.py

# Check architecture fitness thresholds (APSS-based, reads .topology/metrics/)
fitness-check: aps-build check-untyped-dicts
    # Always regenerate topology before checking — never validate against stale data
    just topology-analyze
    @echo "Checking architecture fitness thresholds..."
    {{_aps_bin}} run fitness validate .
    @echo "✅ Fitness threshold checks passed"

# Check structural & ES invariants (pytest-based, AST analysis)
fitness-invariants:
    @echo "Checking structural & ES invariants..."
    uv run pytest ci/fitness/ -v --tb=short -m architecture
    @echo "✅ Invariant checks passed"

# All fitness checks
fitness: fitness-check fitness-invariants

# Run fitness with verbose output (invariant tests only)
fitness-report:
    @echo "Architectural fitness report..."
    uv run pytest ci/fitness/ -v --tb=long -s

# Run VSA validation (requires event-sourcing-platform submodule)
vsa-validate:
    @echo "🔍 Running VSA validation..."
    vsa validate
    @echo "✅ VSA validation passed"

# --- Topology (APS Code Topology Standard) ---

# Path to APS CLI binary
_aps_bin := "lib/agent-paradise-standards-system/target/release/aps"

# Build APS CLI (cached — only rebuilds when source changes)
aps-build:
    @if [ ! -f {{_aps_bin}} ] || [ lib/agent-paradise-standards-system/Cargo.lock -nt {{_aps_bin}} ]; then \
        echo "🔨 Building APS CLI..."; \
        cargo build --release --manifest-path lib/agent-paradise-standards-system/Cargo.toml -p aps-cli; \
    else \
        echo "✅ APS CLI already built"; \
    fi

# Regenerate .topology/ artifacts from current codebase
topology-analyze: aps-build
    @echo "🔍 Analyzing codebase topology..."
    {{_aps_bin}} run topology analyze . --output .topology --seed 42
    @echo "✅ Topology artifacts generated"

# Generate CodeCity and 3D visualizations
topology-viz: aps-build
    @echo "🎨 Generating topology visualizations..."
    {{_aps_bin}} run topology viz .topology --type all --output .topology/viz/
    @echo "✅ Visualizations generated in .topology/viz/"

# Full topology regeneration (analyze + visualize)
topology: topology-analyze topology-viz

# Regenerate topology on demand (topology is no longer committed — #293)
topology-check: topology-analyze
    @echo "✅ Topology artifacts regenerated"

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

# --- Selfhost Deployment ---

# Pre-flight check: platform, Docker, env, secrets, workspaces
_selfhost-preflight:
    #!/usr/bin/env bash
    set -euo pipefail
    ERRORS=0

    echo "🔍 Selfhost pre-flight checks"
    echo ""

    # --- Platform & Docker ---
    echo "Platform: {{_os}} / {{_arch}}"
    if [[ "{{_os}}" == "Darwin" ]]; then
        echo "  macOS detected"
        if ! docker info &>/dev/null; then
            echo "  ❌ Docker is not running. Start Docker Desktop first."
            exit 1
        fi
        if [[ "{{_arch}}" == "arm64" ]]; then
            echo "  Apple Silicon — first event-store build may take 5-10 min"
        fi
    elif [[ "{{_os}}" == "Linux" ]]; then
        echo "  Linux detected"
        if ! docker info &>/dev/null; then
            echo "  ❌ Docker is not running or user not in docker group"
            exit 1
        fi
    fi

    # --- Environment files ---
    if [ ! -f .env ]; then
        echo "  ❌ .env not found (application config). Run 'just onboard' or copy from .env.example"
        ERRORS=$((ERRORS + 1))
    else
        echo "  ✅ .env (application config)"
    fi
    if [ ! -f infra/.env ]; then
        echo "  ❌ infra/.env not found (infrastructure config). Run 'just onboard' or copy from infra/.env.example"
        ERRORS=$((ERRORS + 1))
    else
        echo "  ✅ infra/.env (infrastructure config)"
    fi

    # --- Docker secrets ---
    for secret in db-password redis-password minio-password; do
        if [ ! -f "infra/docker/secrets/${secret}.secret" ]; then
            # Backward compat: check .txt extension too
            if [ -f "infra/docker/secrets/${secret}.txt" ]; then
                echo "  ⚠️  infra/docker/secrets/${secret}.txt found (legacy). Rename to .secret extension."
            else
                echo "  ❌ infra/docker/secrets/${secret}.secret missing. Run 'just onboard' to generate."
                ERRORS=$((ERRORS + 1))
            fi
        else
            echo "  ✅ ${secret}.secret"
        fi
    done

    # --- Agent credentials (needed for workflow execution) ---
    source infra/scripts/selfhost-env.sh 2>/dev/null || true
    if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        echo "  ⚠️  No agent credentials found (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY)."
        echo "     Workflows that spawn agent containers will fail."
        echo "     Set one in infra/.env or your shell environment."
    else
        echo "  ✅ Agent credentials"
    fi

    # --- Workspaces directory ---
    mkdir -p workspaces
    echo "  ✅ workspaces/"

    if [ "$ERRORS" -gt 0 ]; then
        echo ""
        echo "❌ ${ERRORS} pre-flight check(s) failed. Fix the above issues and retry."
        exit 1
    fi
    echo ""

# Start self-hosted Syn137 stack (no Cloudflare)
selfhost-up: _selfhost-preflight _workspace-check
    #!/usr/bin/env bash
    set -euo pipefail
    source infra/scripts/selfhost-env.sh
    echo "🚀 Starting Syn137 self-host stack..."
    {{compose_selfhost}} up -d --build
    echo ""
    echo "⏳ Waiting for services to be ready..."
    uv run python infra/scripts/health_check.py --wait --timeout 180 || true
    echo ""
    echo "🌱 Seeding data..."
    just selfhost-seed || echo "   ⚠️ Seed skipped (data may already exist)"
    echo ""
    just selfhost-status

# Start self-hosted Syn137 stack with Cloudflare Tunnel (recommended)
selfhost-up-tunnel: _selfhost-preflight _workspace-check
    #!/usr/bin/env bash
    set -euo pipefail
    source infra/scripts/selfhost-env.sh
    echo "🚀 Starting Syn137 self-host stack with Cloudflare Tunnel..."
    {{compose_selfhost_cf}} up -d --build
    echo ""
    echo "⏳ Waiting for services to be ready..."
    uv run python infra/scripts/health_check.py --wait --timeout 180 || true
    echo ""
    echo "🌱 Seeding data..."
    just selfhost-seed || echo "   ⚠️ Seed skipped (data may already exist)"
    echo ""
    just selfhost-status
    echo ""
    echo "🔒 Tunnel auth reminder:"
    echo "   Ensure your Cloudflare tunnel routes to http://gateway:8081 (not port 80)"
    echo "   Port 8081 requires basic auth when SYN_API_PASSWORD is set."
    echo "   Update: Zero Trust → Networks → Connectors → Create a tunnel → Select Cloudflared"

# Stop self-host stack (auto-detects Cloudflare Tunnel)
selfhost-down:
    #!/usr/bin/env bash
    set -euo pipefail
    source infra/scripts/selfhost-env.sh
    echo "Stopping Syn137 self-host stack..."
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}}}' 2>/dev/null | grep -q .; then
        echo "  (Cloudflare Tunnel detected)"
        {{compose_selfhost_cf}} down
    else
        {{compose_selfhost}} down
    fi

# Check self-host stack status (auto-detects tunnel)
selfhost-status:
    #!/usr/bin/env bash
    set -euo pipefail
    source infra/scripts/selfhost-env.sh
    echo "📊 Syn137 Self-Host Status"
    echo "======================="
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}}}' 2>/dev/null | grep -q .; then
        echo "  (Cloudflare Tunnel detected)"
        {{compose_selfhost_cf}} ps
    else
        {{compose_selfhost}} ps
    fi
    echo ""
    echo "Access Points:"
    uv run python infra/scripts/print_access_urls.py

# View self-host logs (all services or specific service, auto-detects tunnel)
selfhost-logs *service:
    #!/usr/bin/env bash
    set -euo pipefail
    source infra/scripts/selfhost-env.sh
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}}}' 2>/dev/null | grep -q .; then
        {{compose_selfhost_cf}} logs -f {{service}}
    else
        {{compose_selfhost}} logs -f {{service}}
    fi

# Restart specific self-host service
selfhost-restart service:
    @echo "Restarting {{service}}..."
    @{{compose_selfhost}} restart {{service}}

# Seed workflows and triggers into selfhost stack
# Runs seed scripts in a temporary API container (DB ports not exposed to host)
selfhost-seed:
    #!/usr/bin/env bash
    set -euo pipefail
    source infra/scripts/selfhost-env.sh
    echo "🌱 Seeding workflows..."
    {{compose_selfhost}} run --rm \
      -v "$(pwd)/scripts:/app/scripts:ro" \
      -v "$(pwd)/workflows:/app/workflows:ro" \
      api \
      python /app/scripts/seed_workflows.py --dir /app/workflows/examples
    echo "🌱 Seeding triggers..."
    {{compose_selfhost}} run --rm \
      -v "$(pwd)/scripts:/app/scripts:ro" \
      -v "$(pwd)/workflows:/app/workflows:ro" \
      api \
      python /app/scripts/seed_triggers.py
    echo "✅ Seeding complete"

# Pull latest code, rebuild, and restart self-host (auto-detects tunnel)
selfhost-update:
    #!/usr/bin/env bash
    set -euo pipefail
    source infra/scripts/selfhost-env.sh
    # Detect Cloudflare tunnel
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}}}' 2>/dev/null | grep -q .; then
        COMPOSE="{{compose_selfhost_cf}}"
        echo "  (Cloudflare Tunnel detected)"
    else
        COMPOSE="{{compose_selfhost}}"
    fi
    echo "⬆️ Updating Syn137 self-host..."
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
    source infra/scripts/selfhost-env.sh
    echo "⚠️  WARNING: This will delete ALL data including the database!"
    echo "Press Ctrl+C within 5 seconds to cancel..."
    sleep 5
    if docker ps --filter "name=cloudflared" --format '{{{{.Names}}}}' 2>/dev/null | grep -q .; then
        echo "  (Cloudflare Tunnel detected)"
        {{compose_selfhost_cf}} down -v
    else
        {{compose_selfhost}} down -v
    fi
    just selfhost-up

# --- Secrets ---

# Store 1Password service account token in macOS Keychain (vault-specific)
secrets-store-token:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$(uname -s)" != "Darwin" ]; then
        echo "❌ This command is macOS-only. On Linux, export the env var instead:"
        echo "   export OP_SERVICE_ACCOUNT_TOKEN_<VAULT_UPPER>=<token>"
        exit 1
    fi
    # Source both .env files (APP_ENVIRONMENT lives in root .env)
    if [ -f .env ]; then set -a && source .env && set +a; fi
    if [ -f infra/.env ]; then set -a && source infra/.env && set +a; fi
    # Derive vault from APP_ENVIRONMENT
    case "${APP_ENVIRONMENT:-}" in
        development) _OP_VAULT="syn137-dev" ;;
        production)  _OP_VAULT="syn137-prod" ;;
        beta)        _OP_VAULT="syn137-beta" ;;
        staging)     _OP_VAULT="syn137-staging" ;;
        *)
            echo "❌ APP_ENVIRONMENT not set or unknown in .env"
            echo "   Set it first: APP_ENVIRONMENT=development"
            exit 1 ;;
    esac
    _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$_OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
    _SVC="SYN_${_VK}"
    echo "Storing 1Password token for vault: $_OP_VAULT"
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
    # Source both .env files (APP_ENVIRONMENT lives in root .env)
    if [ -f .env ]; then set -a && source .env && set +a; fi
    if [ -f infra/.env ]; then set -a && source infra/.env && set +a; fi
    # Derive vault from APP_ENVIRONMENT
    case "${APP_ENVIRONMENT:-}" in
        development) _OP_VAULT="syn137-dev" ;;
        production)  _OP_VAULT="syn137-prod" ;;
        beta)        _OP_VAULT="syn137-beta" ;;
        staging)     _OP_VAULT="syn137-staging" ;;
        *)
            echo "❌ APP_ENVIRONMENT not set or unknown in .env"
            exit 1 ;;
    esac
    _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$_OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
    _SVC="SYN_${_VK}"
    security delete-generic-password -a "$USER" -s "$_SVC" 2>/dev/null \
        && echo "✅ Deleted: $_SVC" \
        || echo "⚠️  Not found: $_SVC"

# Push secrets to 1Password vault (selfhost only — uses syn-ctl)
secrets-push:
    @echo "Push secrets to 1Password via syn-ctl:"
    @echo "  cd ~/.syntropic137 && ./syn-ctl secrets-push"
    @echo ""
    @echo "For dev environments, use: just onboard-dev --1password"

# Pull secrets from 1Password vault (selfhost only — uses syn-ctl)
secrets-pull:
    @echo "Pull secrets from 1Password via syn-ctl:"
    @echo "  cd ~/.syntropic137 && ./syn-ctl secrets-pull"
    @echo ""
    @echo "For dev environments, use: just onboard-dev --1password"

# --- Health ---

# Run health checks on all services
health-check:
    @uv run python infra/scripts/health_check.py

# Wait for all services to be ready
health-wait timeout="120":
    @uv run python infra/scripts/health_check.py --wait --timeout {{timeout}}

# Health check with JSON output (for CI/CD)
health-json:
    @uv run python infra/scripts/health_check.py --json

# --- Documentation ---

# Generate architecture diagram (SVG from VSA manifest)
diagram:
    @echo "🏗️  Generating architecture diagrams..."
    @cd lib/event-sourcing-platform/vsa/vsa-visualizer && npm run build > /dev/null 2>&1
    @node lib/event-sourcing-platform/vsa/vsa-visualizer/dist/index.js .topology/syn-manifest.json --format svg --type architecture --output docs/architecture

# Generate CLI reference docs from Node CLI command metadata
docs-cli-gen:
    @echo "📄 Generating CLI reference docs..."
    @cd apps/syn-cli-node && pnpm run generate:docs

# Start docs site dev server (regenerates CLI docs first)
docs: docs-cli-gen
    cd apps/syn-docs && pnpm run dev

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

# Regenerate all derived artifacts and fail if any are uncommitted.
# Runs `just codegen` once, then checks architecture docs, CLI docs, and API artifacts.
docs-sync:
    @echo "🔄 Regenerating architecture documentation..."
    @uv run python scripts/generate-architecture-docs.py > /tmp/docs-gen.txt 2>&1
    @if git diff --quiet docs/architecture/projection-subscriptions.md docs/architecture/event-flows/README.md README.md 2>/dev/null; then \
        echo "✅ Architecture docs are up-to-date"; \
    else \
        echo "❌ Architecture docs need to be committed:"; \
        echo "   git add docs/architecture/ README.md && git commit -m 'docs: update generated architecture docs'"; \
        exit 1; \
    fi
    @echo "🔄 Running codegen (CLI docs + OpenAPI spec + API docs + CLI types)..."
    @just codegen > /dev/null 2>&1
    @if git diff --quiet apps/syn-docs/content/docs/cli/ 2>/dev/null && [ -z "$(git ls-files --others --exclude-standard apps/syn-docs/content/docs/cli/)" ]; then \
        echo "✅ CLI docs are up-to-date"; \
    else \
        echo "❌ CLI docs need to be committed:"; \
        echo "   Run 'just codegen' and commit the changes."; \
        exit 1; \
    fi
    @if git diff --quiet apps/syn-docs/openapi.json apps/syn-docs/content/docs/api/ apps/syn-cli-node/src/generated/api-types.ts 2>/dev/null && [ -z "$(git ls-files --others --exclude-standard apps/syn-docs/content/docs/api/)" ]; then \
        echo "✅ API docs and CLI types are up-to-date"; \
    else \
        echo "❌ API artifacts need to be committed:"; \
        echo "   Run 'just codegen' and commit the changes."; \
        exit 1; \
    fi

# Regenerate ALL derived artifacts: CLI docs, OpenAPI spec, API docs, CLI types.
# Single command after changing any Pydantic model, API route, or CLI command.
# Pipeline: CLI commands → CLI docs, FastAPI app → openapi.json → API docs MDX → CLI TS types
codegen: docs-cli-gen
    @echo "📄 Extracting OpenAPI spec from FastAPI..."
    uv run python scripts/extract_openapi.py
    @echo "📄 Generating API reference docs..."
    cd apps/syn-docs && pnpm run generate:openapi
    @echo "📄 Generating CLI TypeScript types..."
    cd apps/syn-cli-node && pnpm run generate:types
    @echo "✅ All generated artifacts up to date"

# Build docs site (codegen + Next.js build, for deployment)
docs-site-build: codegen
    cd apps/syn-docs && pnpm run build

# --- Utilities ---

# Seed workflows from YAML files
seed-workflows: _ensure-env
    #!/usr/bin/env bash
    uv run python scripts/seed_workflows.py

# Seed trigger presets (self-healing, review-fix)
seed-triggers: _ensure-env
    #!/usr/bin/env bash
    uv run python scripts/seed_triggers.py

# Seed organization, system, and repos
seed-organization: _ensure-env
    #!/usr/bin/env bash
    uv run python scripts/seed_organization.py

# Seed all data (workflows + triggers + organization)
seed-all: seed-workflows seed-triggers seed-organization

# Initialize git submodules
submodules-init:
    git submodule update --init --recursive

# Update git submodules to latest
submodules-update:
    git submodule update --remote --merge

# Generate .env.example from Settings class
gen-env:
    uv run python scripts/generate_env_example.py

# Generate published Docker Compose (docker-compose.syntropic137.yaml) from base + selfhost
gen-compose:
    uv run python scripts/generate_published_compose.py

# Check published compose is up to date (CI mode — fails if stale)
check-compose:
    uv run python scripts/generate_published_compose.py --check

# Generate llms.txt from API docs
generate-llms-txt:
    uv run python scripts/generate_llms_txt.py

# Validate event store by querying PostgreSQL for stored events
validate-events:
    uv run python scripts/validate_event_store.py

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

# Update dependencies to latest versions
update:
    uv lock --upgrade
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
    {{compose_dev}} down -v 2>/dev/null || true
    @echo "Cleanup complete."

# Add a new package to the workspace
new-package name:
    @echo "Creating package: {{name}}"
    mkdir -p packages/{{name}}/src/$(echo {{name}} | tr '-' '_')/
    mkdir -p packages/{{name}}/tests/
    echo "[project]\nname = \"{{name}}\"\nversion = \"0.1.0\"\nrequires-python = \">=3.12\"\ndependencies = []\n\n[build-system]\nrequires = [\"uv_build>=0.9.13\"]\nbuild-backend = \"uv_build\"" > packages/{{name}}/pyproject.toml
    echo "\"\"\"{{name}} package.\"\"\"" > packages/{{name}}/src/$(echo {{name}} | tr '-' '_')/__init__.py
    @echo "Package created at packages/{{name}}"

# Reconfigure GitHub App (change repos, permissions, or recreate)
github-reconfigure:
    @echo "To reconfigure or recreate a GitHub App, use the NPX setup CLI:"
    @echo ""
    @echo "  npx @syntropic137/setup init --skip-docker"
    @echo ""
    @echo "See https://github.com/syntropic137/syntropic137-npx for documentation."

# --- Security & Audit ---

# Run all security and dependency audits
audit: security-audit deps-audit-py deps-audit-npm
    @echo ""
    @echo "✅ All security audits complete"

# Run infrastructure security audit (env vars, secrets, network)
security-audit:
    @uv run python infra/scripts/health_check.py --json
    @echo ""
    @echo "For a full security posture review see: docs/security-practices.md"

# Audit Python dependencies against PyPI advisory database
deps-audit-py:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Python Dependency Audit ==="
    uv tool install pip-audit==2.7.3 --quiet
    uv export --format requirements-txt --no-hashes --frozen --quiet \
        | uv tool run pip-audit --disable-pip -r /dev/stdin

# Audit Node.js dependencies via OSV Scanner (same tool as CI)
deps-audit-npm:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Node.js Dependency Audit (OSV) ==="
    exit_code=0
    # Scan the same lock files as CI's OSV Scanner job.
    # All Node packages standardized on pnpm — single root lock file.
    for lockfile in \
        pnpm-lock.yaml; do
        if [ -f "$lockfile" ]; then
            echo "--- $lockfile ---"
            if command -v osv-scanner &>/dev/null; then
                osv-scanner --lockfile="$lockfile" || exit_code=1
            else
                echo "⚠️  osv-scanner not installed. Install: brew install osv-scanner"
                exit_code=1
            fi
        fi
    done
    exit $exit_code

# Show dependency trees to identify reduction targets
deps-tree:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Python Dependency Tree ==="
    uv tree --depth 2
    echo ""
    echo "=== Python: total packages ==="
    echo "  $(grep -c '^\[\[package\]\]' uv.lock) packages in uv.lock"
    echo ""
    echo "=== Node.js: package counts ==="
    for dir in apps/syn-dashboard-ui apps/syn-docs; do
        if [ -f "$dir/pnpm-lock.yaml" ]; then
            count=$(grep -c 'resolution:' "$dir/pnpm-lock.yaml" 2>/dev/null || echo "?")
            echo "  $dir: ~$count packages (pnpm)"
        fi
    done

# Build the egress proxy image
proxy-build:
    docker build -t syn-egress-proxy:latest -f docker/egress-proxy/Dockerfile docker/egress-proxy/

# Start the egress proxy
proxy-start:
    #!/usr/bin/env bash
    set -euo pipefail
    PROXY_PORT="${SYN_PROXY_PORT:-18080}"
    docker rm -f syn-egress-proxy 2>/dev/null || true
    docker run -d --name syn-egress-proxy -p "${PROXY_PORT}:8080" \
        -e ALLOWED_HOSTS="api.anthropic.com,github.com,api.github.com,pypi.org,files.pythonhosted.org" \
        syn-egress-proxy:latest
    echo "✓ Egress proxy started on port ${PROXY_PORT}"

# --- Internal Helpers (hidden from --list) ---

# Build the dev compose command, auto-including cloudflare overlay when tunnel token is set.
# Usage in bash: _COMPOSE=$(_dev_compose_cmd)
# Must be called AFTER infra env vars are loaded.
_dev-compose-cmd:
    @if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then \
        echo "{{compose_dev_cf}}"; \
    else \
        echo "{{compose_dev}}"; \
    fi

# Create .env files from templates if they don't exist (idempotent)
# Sets dev defaults so `just dev` works immediately without onboard-dev
_ensure-env:
    @if [ ! -f .env ]; then \
        cp .env.example .env; \
        sed -i.bak 's|^APP_ENVIRONMENT=.*|APP_ENVIRONMENT=development|' .env && rm -f .env.bak; \
        sed -i.bak 's|^ESP_EVENT_STORE_DB_URL=.*|ESP_EVENT_STORE_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn|' .env && rm -f .env.bak; \
        sed -i.bak 's|^SYN_OBSERVABILITY_DB_URL=.*|SYN_OBSERVABILITY_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn|' .env && rm -f .env.bak; \
        echo "📝 Created .env from .env.example (dev defaults)"; \
    fi
    @if [ ! -f infra/.env ] && [ -f infra/.env.example ]; then \
        cp infra/.env.example infra/.env; \
        echo "📝 Created infra/.env from infra/.env.example"; \
    fi

# Check .env for common misconfigurations and warn loudly
_env-check: _ensure-env
    #!/usr/bin/env bash
    eval "$(uv run python scripts/resolve_infra_env.py)"
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
    if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
        _H="${SYN_PUBLIC_HOSTNAME:-}"; _H="${_H#https://}"; _H="${_H#http://}"; _H="${_H%/}"
        if [ -n "$_H" ]; then
            echo "   Webhook delivery: Cloudflare tunnel (${_H})"
        else
            echo "   ✅ Webhook delivery: Cloudflare tunnel"
        fi
    elif [ -n "${DEV__SMEE_URL:-}" ]; then
        echo "   ✅ Webhook delivery: smee.io proxy"
    else
        echo "   ⚠️  WARNING: No webhook delivery configured"
        echo "               GitHub webhooks will not reach your local stack."
        echo "               Fix: just onboard-dev --tunnel  OR  add DEV__SMEE_URL to .env"
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

# Start webhook delivery — Cloudflare tunnel (if configured) or Smee proxy
_webhook-start:
    #!/usr/bin/env bash
    eval "$(uv run python scripts/resolve_infra_env.py)"

    # Option 1: Cloudflare tunnel — token or domain configured
    if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ] || [ -n "${SYN_PUBLIC_HOSTNAME:-}" ]; then
        _HOSTNAME="${SYN_PUBLIC_HOSTNAME#https://}"
        _HOSTNAME="${_HOSTNAME#http://}"
        _HOSTNAME="${_HOSTNAME%/}"
        # Verify tunnel container is running
        if docker ps --format '{{"{{"}}.Names{{"}}"}}' 2>/dev/null | grep -q 'cloudflared'; then
            echo "5  Webhooks via Cloudflare tunnel (${_HOSTNAME})"
        else
            echo "5️⃣  ⚠️  Cloudflare tunnel not running — starting it..."
            $(just _dev-compose-cmd) up -d cloudflared
        fi
        echo "   Webhook URL: https://${_HOSTNAME}/webhooks/github"
        echo "   💡 Tunnel service URL must be: http://api:8000 (dev) or http://gateway:8081 (selfhost)"
        exit 0
    fi

    # Option 2: Smee proxy
    if [ -n "${DEV__SMEE_URL:-}" ]; then
        uv run python scripts/manage_webhook_url.py --mode dev || true
        pkill -f "smee-client.*${DEV__SMEE_URL}" 2>/dev/null || true
        echo "5️⃣  Starting webhook proxy (smee.io → localhost:9137)..."
        npx -y smee-client --url "$DEV__SMEE_URL" --target http://localhost:9137/webhooks/github --path /webhooks/github > /tmp/smee.log 2>&1 &
        echo "   🔗 Webhook proxy: $DEV__SMEE_URL → http://localhost:9137/webhooks/github"
        exit 0
    fi

    # Neither configured
    echo "   ⚠️  No webhook delivery configured"
    echo "   💡 Options:"
    echo "      • just onboard-dev --tunnel   (Cloudflare tunnel)"
    echo "      • Add DEV__SMEE_URL=<url> to .env (smee.io proxy)"

# Stop webhook delivery (smee proxy + restore prod webhook URL)
_webhook-stop:
    @-uv run python scripts/manage_webhook_url.py --mode prod 2>/dev/null || true
    @-pkill -f "smee-client" 2>/dev/null || true

# Check if workspace image exists AND matches current submodule commit
# Poka-yoke: Automatically rebuilds if agentic-primitives was updated
_workspace-check:
    #!/usr/bin/env bash
    set -euo pipefail
    IMAGE="agentic-workspace-claude-cli:latest"

    # Auto-init submodules if not yet initialized (worktree-safe)
    if [ ! -f lib/agentic-primitives/.git ] && [ ! -d lib/agentic-primitives/.git ]; then
        echo "📦 Submodules not initialized — initializing..."
        just submodules-init
    fi

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

# --- Release (Local) ---
# Build and push container images to GHCR from your local machine.
# Useful when CI is slow or broken. Requires: gh auth with write:packages scope.

# Bump version across all 11 package files
bump-version version:
    python3 scripts/workflows/bump_version.py {{version}}

# Validate all 11 package files have the same version
check-version:
    python3 scripts/workflows/bump_version.py --check

registry := "ghcr.io/syntropic137"

# Build and push core container images locally (skips event-store and agentic-workspace — use release-retag for those)
release-local version:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🚀 Local release: {{version}}"
    echo ""

    # Login to GHCR
    gh auth token | docker login ghcr.io -u syntropic137 --password-stdin
    echo ""

    # Ensure buildx builder exists
    docker buildx inspect multiarch >/dev/null 2>&1 || docker buildx create --name multiarch
    docker buildx use multiarch

    # Images to build (order: fast first)
    FAILED=()
    for image in token-injector sidecar-proxy syn-collector syn-dashboard-ui syn-api syn-gateway; do
        case "$image" in
            token-injector)   dockerfile="docker/token-injector/Dockerfile"; context="docker/token-injector" ;;
            sidecar-proxy)    dockerfile="docker/sidecar-proxy/Dockerfile"; context="docker/sidecar-proxy" ;;
            syn-collector)    dockerfile="packages/syn-collector/Dockerfile"; context="." ;;
            syn-dashboard-ui) dockerfile="apps/syn-dashboard-ui/Dockerfile"; context="." ;;
            syn-api)          dockerfile="infra/docker/images/syn-api/Dockerfile"; context="." ;;
            syn-gateway)      dockerfile="infra/docker/images/gateway/Dockerfile"; context="." ;;
        esac
        echo "📦 Building $image..."
        if docker buildx build --platform linux/amd64,linux/arm64 \
            -f "$dockerfile" \
            -t "{{registry}}/$image:{{version}}" \
            --push "$context"; then
            echo "✅ $image pushed"
        else
            echo "❌ $image failed"
            FAILED+=("$image")
        fi
        echo ""
    done

    # Summary
    echo "=== Release Summary ==="
    echo "Version: {{version}}"
    echo "Registry: {{registry}}"
    if [ ${#FAILED[@]} -eq 0 ]; then
        echo "✅ All images pushed successfully"
    else
        echo "❌ Failed: ${FAILED[*]}"
        exit 1
    fi

# Re-tag an existing image version without rebuilding (e.g., event-store)
release-retag image from to:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🏷️  Re-tagging {{registry}}/{{image}}:{{from}} → {{to}}"
    gh auth token | docker login ghcr.io -u syntropic137 --password-stdin
    docker buildx imagetools create \
        "{{registry}}/{{image}}:{{from}}" \
        --tag "{{registry}}/{{image}}:{{to}}"
    echo "✅ Done"

# Upload selfhost assets to a GitHub release
release-assets version:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "📎 Uploading selfhost assets to {{version}}"
    gh release upload "{{version}}" \
        docker/docker-compose.syntropic137.yaml \
        docker/selfhost.env.example \
        docker/selfhost-entrypoint.sh \
        syn-ctl \
        --repo syntropic137/syntropic137 --clobber
    echo "✅ Assets uploaded"

# Full local release: build images + re-tag event-store + upload assets
# Usage: just release-local-full v0.17.1 v0.17.0
#   version: the new tag to create
#   from: existing tag to re-tag event-store/agentic-workspace from (they rarely change)
release-local-full version from:
    #!/usr/bin/env bash
    set -euo pipefail
    just release-local "{{version}}"
    just release-retag event-store "{{from}}" "{{version}}"
    just release-retag agentic-workspace "{{from}}" "{{version}}"
    just release-assets "{{version}}"
    echo ""
    echo "🎉 Full release complete: {{version}}"
    echo "   Test with: SYN_VERSION={{version}} docker compose -f docker/docker-compose.syntropic137.yaml pull"
