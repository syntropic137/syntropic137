#!/usr/bin/env bash
# End-to-end smoke for #726 PR2 (workspace materialization + --plugin-dir).
# Verifies that plugins declared in workflow YAML actually land inside the
# agent workspace and the claude CLI is invoked with the matching
# --plugin-dir flags. Reuses the validated hello-world plugin from
# validation-experiment/.
#
# Per ADR-066: this script does no git work; it inlines the local
# hello-world plugin tree into the new POST /claude-plugins/registrations
# endpoint directly, so it can run without pushing the fixture to a git
# host. The "source_url" we tell the API is purely an identifier.
#
# Prerequisites:
#   - just dev is running; check `docker ps | grep syn-api` for the port
#   - SYN_API_URL points at the running stack root (e.g. http://localhost:9137)
#   - SYN_API_PASSWORD is set in the shell
#
# What it verifies:
#   1. The local hello-world plugin tree registers via the new thin endpoint
#   2. The plugin lands in the lock and can be added to the global set
#   3. A workflow declaring the plugin installs cleanly (pre-flight passes)
#   4. Triggering the workflow runs an agent phase whose transcript contains
#      "__SYN_HELLO_726__" emitted by the hello-world greet skill
#
# Cost: 1 small MinIO upload + 1 short claude session at default pricing.

set -euo pipefail

: "${SYN_API_URL:?Set SYN_API_URL to the running stack root}"
: "${SYN_API_PASSWORD:?Set SYN_API_PASSWORD for the dev stack}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="${HERE}/validation-experiment/hello-world"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

PLUGIN_NAME="hello-world"
PLUGIN_VERSION="0.0.1"
SOURCE_URL="local://hello-world"  # synthetic identifier; not actually fetched
SENTINEL="__SYN_HELLO_726__"

curl_api() {
    curl -fsS -u "admin:${SYN_API_PASSWORD}" "$@"
}

step() { echo; echo "=== $* ==="; }
fail() { echo "FAIL: $*" >&2; exit 1; }

step "0. /health"
curl_api "${SYN_API_URL}/api/v1/health" | jq -e '.status == "healthy"' >/dev/null \
  || fail "API not healthy"
echo "OK"

step "1. build register body from local hello-world tree"
[ -d "${PLUGIN_DIR}" ] || fail "plugin tree missing at ${PLUGIN_DIR}"

python3 -c "
import base64, json, os
root = '${PLUGIN_DIR}'
files = []
for dirpath, _, filenames in os.walk(root):
    for f in sorted(filenames):
        full = os.path.join(dirpath, f)
        rel = os.path.relpath(full, root)
        with open(full, 'rb') as fh:
            content = fh.read()
        files.append({'rel_path': rel, 'content_b64': base64.b64encode(content).decode('ascii')})

with open(os.path.join(root, '.claude-plugin', 'plugin.json')) as fh:
    manifest = json.load(fh)

body = {
    'source_url': '${SOURCE_URL}',
    'version': '${PLUGIN_VERSION}',
    'name': '${PLUGIN_NAME}',
    'manifest': manifest,
    'files': files,
}
print(json.dumps(body))
" > "${TMP}/register.json"

FILE_COUNT=$(jq '.files | length' "${TMP}/register.json")
echo "${FILE_COUNT} files to upload"

step "2. POST /claude-plugins/registrations"
REG_RESP=$(curl_api -X POST "${SYN_API_URL}/api/v1/claude-plugins/registrations" \
    -H "Content-Type: application/json" \
    --data-binary "@${TMP}/register.json")
echo "${REG_RESP}" | jq .
REG_SHA=$(echo "${REG_RESP}" | jq -r '.sha256')
[ -n "${REG_SHA}" ] && [ "${REG_SHA}" != "null" ] || fail "register response missing sha256"

step "3. POST /claude-plugins/global (retry on 404 — known projection-sync lag)"
# Lock projection takes ~1s to catch up from the registrations event.
# Retry up to 5 times. Captured as a follow-up: registrations should
# return only after the projection has caught up, OR global add should
# accept the sha directly to avoid the lookup race.
for attempt in 1 2 3 4 5; do
    if curl_api -X POST "${SYN_API_URL}/api/v1/claude-plugins/global" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"${PLUGIN_NAME}\",\"version\":\"${PLUGIN_VERSION}\"}" 2>/dev/null | jq .; then
        break
    fi
    [ "${attempt}" -eq 5 ] && fail "global add still 404 after 5 retries"
    echo "  attempt ${attempt} failed; sleeping 2s..."
    sleep 2
done

step "4. Install a one-phase workflow that declares the plugin"
WID="pr2-hello-world-$(date +%s)"
cat > "${TMP}/workflow.yaml" <<YAML
id: ${WID}
name: PR2 hello world smoke
type: research
description: smoke that triggers an execution to verify materialization
classification: simple
project_name: Syntropic137
requires_repos: false
claude_plugins:
  - source: ${SOURCE_URL}
    version: ${PLUGIN_VERSION}
    name: ${PLUGIN_NAME}
phases:
  - id: greet
    name: Greet
    order: 1
    execution_type: sequential
    prompt_template: "Use the greet skill to greet me."
    timeout_seconds: 300
YAML

curl_api -X POST "${SYN_API_URL}/api/v1/workflows/from-yaml" \
    -H "Content-Type: application/x-yaml" \
    --data-binary "@${TMP}/workflow.yaml" | jq .

step "5. Trigger workflow execution (POST /workflows/{id}/execute)"
EXEC_RESP=$(curl_api -X POST "${SYN_API_URL}/api/v1/workflows/${WID}/execute" \
    -H "Content-Type: application/json" \
    -d '{"task":"greet me"}')
echo "${EXEC_RESP}" | jq .
EXEC_ID=$(echo "${EXEC_RESP}" | jq -r '.execution_id // .id // empty')
[ -n "${EXEC_ID}" ] || fail "execution dispatch did not return an id"

step "6. Poll execution status (max 5 min)"
deadline=$(( $(date +%s) + 300 ))
last_status=""
STATUS=""
while [[ $(date +%s) -lt ${deadline} ]]; do
    # Tolerate transient 404 from projection lag right after dispatch
    RESP=$(curl -sS -u "admin:${SYN_API_PASSWORD}" -w "\n%{http_code}" "${SYN_API_URL}/api/v1/executions/${EXEC_ID}" 2>&1 || true)
    HTTP=$(echo "${RESP}" | tail -1)
    BODY=$(echo "${RESP}" | sed '$d')
    if [ "${HTTP}" = "200" ]; then
        STATUS=$(echo "${BODY}" | jq -r '.status // empty')
    else
        STATUS="pending(${HTTP})"
    fi
    if [ "${STATUS}" != "${last_status}" ]; then
        echo "  status=${STATUS}"
        last_status="${STATUS}"
    fi
    case "${STATUS}" in
        completed|failed|cancelled) break ;;
    esac
    sleep 5
done
[ "${STATUS}" = "completed" ] || fail "execution ended in status ${STATUS:-unknown}, expected completed"

step "7. Fetch execution detail (session_ids live under .phases[])"
EXEC_DETAIL=$(curl_api "${SYN_API_URL}/api/v1/executions/${EXEC_ID}")
echo "${EXEC_DETAIL}" | jq '{status, phases: [.phases[] | {phase_id, status, session_id}]}'

step "8. Search for sentinel in conversation transcripts"
# Phase sessions are inline on the execution detail. The previous top-level
# `.sessions[]` path was a misread - this is the canonical extraction.
SESSION_IDS=$(echo "${EXEC_DETAIL}" | jq -r '.phases[]?.session_id // empty')

found=0
for sid in ${SESSION_IDS}; do
    T=$(curl_api "${SYN_API_URL}/api/v1/conversations/${sid}" 2>/dev/null || true)
    if echo "${T}" | grep -q "${SENTINEL}"; then
        echo "OK: sentinel found in session ${sid} transcript"
        found=1
        break
    fi
done
[ "${found}" = "1" ] || fail "sentinel '${SENTINEL}' NOT found in any session transcript (searched ${SESSION_IDS:-no sessions})"

echo
echo "=== ALL PASS - PR2 e2e smoke green; agent loaded the plugin and invoked the skill ==="
