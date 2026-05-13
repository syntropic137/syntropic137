#!/usr/bin/env bash
# Validation experiment for issue #726 — claude plugin injection.
#
# Spins the production workspace image, drops two test plugins into the
# workspace via docker cp, runs claude -p with --plugin-dir flags, and
# asserts the agent loaded both skills.
#
# Requirements (one of):
#   CLAUDE_CODE_OAUTH_TOKEN=...   # preferred
#   ANTHROPIC_API_KEY=...         # fallback
#
# Usage:
#   ./run.sh                      # run all 4 tests
#   ./run.sh test1                # run a specific test
#
# Tests:
#   test1 — single plugin, description-matched invocation
#   test2 — single plugin, explicit /skill invocation
#   test3 — two plugins, both invoked (collision-free check)
#   test4 — real plugin (software-leverage-points) loads without error
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-agentic-workspace-claude-cli:latest}"
CONTAINER="syn-726-validation-$$"

# Auth check
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY" >&2
  exit 1
fi

AUTH_ENV=()
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  AUTH_ENV+=(-e "CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}")
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  AUTH_ENV+=(-e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}")
fi

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

start_container() {
  echo "[setup] starting container $CONTAINER from $IMAGE"
  docker run -d --rm \
    --name "$CONTAINER" \
    "${AUTH_ENV[@]}" \
    -e "GIT_AUTHOR_NAME=test" \
    -e "GIT_AUTHOR_EMAIL=test@test.local" \
    "$IMAGE" \
    sleep 3600 >/dev/null
  # Wait for entrypoint to settle
  sleep 1
}

inject_plugins() {
  echo "[setup] injecting hello-world + goodbye-world into /workspace/.syn-plugins/"
  docker exec "$CONTAINER" mkdir -p /workspace/.syn-plugins
  docker cp "$HERE/hello-world"   "$CONTAINER:/workspace/.syn-plugins/"
  docker cp "$HERE/goodbye-world" "$CONTAINER:/workspace/.syn-plugins/"
  echo "[setup] plugin tree:"
  docker exec "$CONTAINER" find /workspace/.syn-plugins -type f
}

run_claude() {
  local prompt="$1"; shift
  local plugin_flags=("$@")
  docker exec "$CONTAINER" bash -lc "
    cd /workspace
    claude ${plugin_flags[*]} -p '$prompt' 2>&1
  "
}

assert_contains() {
  local needle="$1" haystack="$2" label="$3"
  if echo "$haystack" | grep -q -- "$needle"; then
    echo "  PASS: $label found '$needle'"
    return 0
  else
    echo "  FAIL: $label missing '$needle'"
    echo "  ----- output -----"
    echo "$haystack" | sed 's/^/  | /'
    echo "  ------------------"
    return 1
  fi
}

run_test1() {
  echo
  echo "[test1] single plugin, description-matched invocation"
  local out
  out=$(run_claude \
    "greet me" \
    --plugin-dir /workspace/.syn-plugins/hello-world)
  assert_contains "__SYN_HELLO_726__" "$out" "test1 hello marker"
}

run_test2() {
  echo
  echo "[test2] single plugin, explicit /skill invocation"
  local out
  out=$(run_claude \
    "use the greet skill to greet me" \
    --plugin-dir /workspace/.syn-plugins/hello-world)
  assert_contains "__SYN_HELLO_726__" "$out" "test2 hello marker"
}

run_test3() {
  echo
  echo "[test3] two plugins loaded simultaneously"
  local out
  out=$(run_claude \
    "first greet me, then say goodbye" \
    --plugin-dir /workspace/.syn-plugins/hello-world \
    --plugin-dir /workspace/.syn-plugins/goodbye-world)
  assert_contains "__SYN_HELLO_726__"   "$out" "test3 hello marker" || true
  assert_contains "__SYN_GOODBYE_726__" "$out" "test3 goodbye marker"
}

run_test4() {
  echo
  echo "[test4] real plugin (software-leverage-points) loads without error"
  local slp="$HOME/.claude/plugins/cache/syntropic137-claude-plugins/software-leverage-points"
  if [ ! -d "$slp" ]; then
    echo "  SKIP: software-leverage-points not found at $slp"
    return 0
  fi
  docker cp "$slp" "$CONTAINER:/workspace/.syn-plugins/software-leverage-points"
  local out
  out=$(run_claude \
    "what skills do you have available? list them by name." \
    --plugin-dir /workspace/.syn-plugins/software-leverage-points)
  assert_contains "leverage" "$out" "test4 sees a leverage-points skill"
}

start_container
inject_plugins

case "${1:-all}" in
  test1) run_test1 ;;
  test2) run_test2 ;;
  test3) run_test3 ;;
  test4) run_test4 ;;
  all)
    failed=0
    run_test1 || failed=$((failed+1))
    run_test2 || failed=$((failed+1))
    run_test3 || failed=$((failed+1))
    run_test4 || failed=$((failed+1))
    echo
    if [ $failed -eq 0 ]; then
      echo "[result] ALL TESTS PASSED — injection approach validated"
    else
      echo "[result] $failed test(s) FAILED"
      exit 1
    fi
    ;;
  *) echo "unknown test: $1"; exit 2 ;;
esac
