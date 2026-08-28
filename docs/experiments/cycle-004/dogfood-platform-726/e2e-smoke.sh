#!/usr/bin/env bash
# End-to-end smoke for #726 Phase B (CLI-driven thin-API plugin install).
#
# Drives the `syn` CLI directly so we exercise the full path:
#   parseClaudePluginRef -> gitClone -> walkPluginTree
#   -> POST /claude-plugins/registrations -> POST /claude-plugins/global
#   -> projection -> GET /claude-plugins ...
#
# Per ADR-066 there is no git inside any API container; the CLI does the
# clone locally and posts inline file payloads.
#
# Prerequisites:
#   - `just dev` is running (dev gateway on http://localhost:9137)
#   - SYN_API_PASSWORD is set in your shell
#   - SYN_API_URL points at the running stack (e.g. http://localhost:9137)
#   - `syn` CLI is on PATH and built (or alias to a local node dist/syn.js)
#
# What it verifies:
#   1. /health is reachable
#   2. claude-plugins routes are present in OpenAPI
#   3. `syn claude-plugin install ... --global` clones and registers a real
#      GitHub repo and enables it globally
#   4. `syn claude-plugin global list` shows the entry
#   5. `syn claude-plugin list` shows the lock entry
#   6. `syn claude-plugin show` prints detail
#   7. `syn claude-plugin global remove` removes from the global set
#   8. `syn workflow install <pkg-with-claude_plugins>` triggers the CLI
#      pre-flight that registers any missing plugins before workflow POST

set -euo pipefail

API_URL="${SYN_API_URL:-http://localhost:9137}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

step() { echo; echo "=== $* ==="; }
fail() { echo "FAIL: $*" >&2; exit 1; }

step "1. /api/v1/health"
# All API paths go through the dev gateway with /api/v1/ prefix (mirrors prod).
# Bare /health is intercepted by Vite as an SPA route and returns index.html.
curl -sf "$API_URL/api/v1/health" | jq -e '.status == "healthy"' >/dev/null \
  || fail "API not healthy"
echo "OK"

step "2. claude-plugins routes in OpenAPI"
curl -sf "$API_URL/api/v1/openapi.json" \
  | jq -e '.paths | keys | map(select(startswith("/claude-plugins"))) | length >= 4' >/dev/null \
  || fail "claude-plugins routes missing from spec"
echo "OK (>= 4 routes)"

step "3. syn claude-plugin install --global (real github repo)"
syn claude-plugin install syntropic137/software-leverage-points@main --global \
  || fail "install --global failed"

step "4. syn claude-plugin global list"
syn claude-plugin global list | tee "$TMP/global-list.txt"
grep -q software-leverage-points "$TMP/global-list.txt" \
  || fail "global list does not include software-leverage-points"

step "5. syn claude-plugin list"
syn claude-plugin list | tee "$TMP/list.txt"
grep -q software-leverage-points "$TMP/list.txt" \
  || fail "list does not include software-leverage-points"

step "6. syn claude-plugin show"
syn claude-plugin show software-leverage-points main

step "7. syn claude-plugin global remove"
syn claude-plugin global remove software-leverage-points

step "8. Workflow install triggers claude-plugin pre-flight"
mkdir -p "$TMP/wf-with-plugins"
cat > "$TMP/wf-with-plugins/workflow.yaml" <<'YAML'
id: test-726-preflight
name: 726 preflight smoke
type: research
description: tiny test workflow with a claude_plugin declaration
classification: simple
project_name: Syntropic137
claude_plugins:
  - syntropic137/software-leverage-points@main
phases:
  - id: noop
    name: noop
    order: 1
    execution_type: sequential
    prompt_template: "say hi"
    timeout_seconds: 60
YAML

syn workflow install "$TMP/wf-with-plugins" \
  || fail "workflow install with claude_plugins did not succeed"

step "9. Verify the pre-flight populated the lock again"
syn claude-plugin list | grep -q software-leverage-points \
  || fail "lock missing software-leverage-points after workflow install pre-flight"

echo
echo "=== ALL PASS - #726 Phase B e2e smoke green ==="
