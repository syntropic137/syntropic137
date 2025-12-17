#!/bin/bash
# PR #28 Pre-Merge Checklist
#
# This script validates that PR #28 is ready for merge.
# Run this before pushing to remote.
#
# Usage:
#   bash scripts/pr_checklist.sh [--quick]
#
# Options:
#   --quick    Skip E2E tests (runs in ~5 minutes instead of ~10)

set -euo pipefail

QUICK_MODE=false
if [[ "${1:-}" == "--quick" ]]; then
    QUICK_MODE=true
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0

# Functions
check_pass() {
    echo -e "${GREEN}✅ $1${NC}"
    ((PASSED++))
}

check_fail() {
    echo -e "${RED}❌ $1${NC}"
    ((FAILED++))
}

check_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

check_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Header
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                   PR #28 Pre-Merge Checklist                    ║"
echo "║            Agent-in-Container Comprehensive Feature             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# 1. Git Status
echo "📋 Step 1: Git Status"
echo "────────────────────"
if git diff --quiet; then
    check_pass "No uncommitted changes"
else
    check_warn "Uncommitted changes exist (OK if intentional)"
fi

# Check branch name
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" == "feat/agent-in-container" ]]; then
    check_pass "On correct branch: $BRANCH"
else
    check_fail "Wrong branch: $BRANCH (should be feat/agent-in-container)"
fi

# Check for main merge conflicts
if git rev-parse --verify main >/dev/null 2>&1; then
    if ! git merge-base --is-ancestor main HEAD; then
        check_warn "Branch not fully merged with main (may need rebase)"
    else
        check_pass "Branch includes all main commits"
    fi
fi
echo ""

# 2. Dependencies
echo "📦 Step 2: Dependencies"
echo "──────────────────────"
if command -v python &> /dev/null; then
    PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
    check_pass "Python available: $PYTHON_VERSION"
else
    check_fail "Python not found in PATH"
fi

if command -v docker &> /dev/null; then
    check_pass "Docker available"
else
    check_fail "Docker not found (needed for E2E tests)"
fi

if uv --version >/dev/null 2>&1; then
    check_pass "uv available"
else
    check_fail "uv not found (needed for dependencies)"
fi
echo ""

# 3. Code Quality
echo "🔍 Step 3: Code Quality Checks"
echo "──────────────────────────────"

# Lint
if uv run ruff check . >/dev/null 2>&1; then
    check_pass "Lint checks passing (ruff)"
else
    check_fail "Lint errors found - run: uv run ruff check ."
fi

# Format
if uv run ruff format --check . >/dev/null 2>&1; then
    check_pass "Code formatting OK"
else
    check_fail "Formatting errors - run: uv run ruff format ."
fi

# Type check
if uv run mypy apps packages >/dev/null 2>&1; then
    check_pass "Type checks passing (mypy)"
else
    check_fail "Type errors found - run: uv run mypy apps packages"
fi
echo ""

# 4. Tests
echo "🧪 Step 4: Test Suite"
echo "────────────────────"
TEST_OUTPUT=$(uv run pytest -q --tb=short 2>&1 || true)
TEST_COUNT=$(echo "$TEST_OUTPUT" | grep -oP '\d+(?= passed)' || echo "0")

if [[ "$TEST_COUNT" -gt "990" ]]; then
    check_pass "Unit tests passing ($TEST_COUNT tests)"
else
    check_fail "Unit tests failing (got $TEST_COUNT, expected >990)"
fi
echo ""

# 5. Docker
echo "🐳 Step 5: Docker Image"
echo "──────────────────────"
if docker image inspect aef-workspace:latest >/dev/null 2>&1; then
    check_pass "Workspace image exists locally"
else
    check_warn "Workspace image not found (will build on first E2E test)"
    echo "  Tip: Run 'just workspace-build' to pre-build"
fi
echo ""

# 6. E2E Tests
echo "🚀 Step 6: E2E Container Tests"
echo "──────────────────────────────"
if [[ "$QUICK_MODE" == "true" ]]; then
    check_info "Skipping E2E tests (--quick mode)"
else
    if python scripts/e2e_agent_in_container_test.py >/dev/null 2>&1; then
        check_pass "E2E container test passed"
    else
        check_fail "E2E container test failed - run: python scripts/e2e_agent_in_container_test.py"
    fi
fi
echo ""

# 7. Files
echo "📁 Step 7: Key Files"
echo "───────────────────"
FILES=(
    "packages/aef-agent-runner/src/aef_agent_runner/__init__.py"
    "packages/aef-domain/src/aef_domain/contexts/workspaces/workspace_aggregate.py"
    "packages/aef-adapters/src/aef_adapters/storage/artifact_storage/minIO_storage.py"
    "scripts/e2e_agent_in_container_test.py"
    "scripts/pre_merge_validation.py"
    "docker/workspace/Dockerfile"
    ".github/workflows/e2e-container.yml"
)

for file in "${FILES[@]}"; do
    if [[ -f "$file" ]]; then
        check_pass "Found: $file"
    else
        check_warn "Missing: $file (may not be critical)"
    fi
done
echo ""

# 8. Documentation
echo "📚 Step 8: Documentation"
echo "──────────────────────"
DOCS=(
    "docs/PR-28-AGENT-IN-CONTAINER.md"
    "docs/adrs/ADR-027-unified-workflow-executor.md"
    "README.md"
)

for doc in "${DOCS[@]}"; do
    if [[ -f "$doc" ]]; then
        check_pass "Found: $doc"
    else
        check_warn "Missing: $doc (may not be critical)"
    fi
done
echo ""

# Summary
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                       Checklist Summary                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo -e "✅ Passed: ${GREEN}$PASSED${NC}"
echo -e "❌ Failed: ${RED}$FAILED${NC}"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✅ All checks passed! Ready to open PR.${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. git add ."
    echo "  2. git commit -m 'feat(container): ...'"
    echo "  3. git push origin feat/agent-in-container"
    echo "  4. Open PR on GitHub"
    echo "  5. Request review from @maintainers"
    echo ""
    exit 0
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}❌ Some checks failed. Fix them before opening PR.${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    exit 1
fi
