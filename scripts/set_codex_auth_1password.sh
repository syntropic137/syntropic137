#!/usr/bin/env bash
# Write ~/.codex/auth.json into the 1Password item the platform reads.
#
# WHY THIS EXISTS
# ---------------
# Codex authenticates with a FILE (~/.codex/auth.json from a ChatGPT-account
# login), not an API key. syn-api stages that file into each workspace during
# setup, reading it from the CODEX_AUTH_JSON setting. That setting is resolved
# from 1Password by scripts/op_env_export.py.
#
# So codex is broken on any environment whose vault lacks the field - which was
# the case for every environment until this script existed. `just codex-auth-clip`
# only copies the value to the clipboard; pasting a 4KB single-line JSON blob
# into a 1Password field by hand is error-prone (a stray newline breaks it).
#
# The secret is never printed. It goes stdin -> op, and the script prints only
# lengths and pass/fail.
#
# USAGE
#   scripts/set_codex_auth_1password.sh [vault]
#
#   vault defaults to syn137-dev. Use `syntropic137` for the selfhost vault.
#
# REQUIREMENTS
#   - `op` CLI authenticated, EITHER by:
#       * an OP_SERVICE_ACCOUNT_TOKEN in the environment (CI / automation), or
#       * `op signin` for your personal account (interactive).
#   - ~/.codex/auth.json present (run `codex login` if not; honours CODEX_HOME).
set -euo pipefail

VAULT="${1:-syn137-dev}"
ITEM="syntropic137-config"
FIELD="CODEX_AUTH_JSON"
AUTH_FILE="${CODEX_HOME:-$HOME/.codex}/auth.json"

if [ ! -f "$AUTH_FILE" ]; then
  echo "error: $AUTH_FILE not found." >&2
  echo "       Run 'codex login' first, or set CODEX_HOME if codex lives elsewhere." >&2
  exit 1
fi

# Compact to one line. A multi-line value round-trips through 1Password and the
# .env loader differently and will silently produce an unusable credential.
value="$(python3 -c '
import json, sys
with open(sys.argv[1]) as fh:
    print(json.dumps(json.load(fh), separators=(",", ":")))
' "$AUTH_FILE")"

if [ -z "$value" ]; then
  echo "error: could not read or compact $AUTH_FILE" >&2
  exit 1
fi

echo "Source:  $AUTH_FILE (${#value} bytes compacted)"
echo "Target:  vault=$VAULT item=$ITEM field=$FIELD"

if ! op item get "$ITEM" --vault "$VAULT" >/dev/null 2>&1; then
  echo "error: item '$ITEM' not found in vault '$VAULT'." >&2
  echo "       Check the vault name, and that your credential can see it:" >&2
  echo "         op vault list" >&2
  exit 1
fi

# `field[password]=` creates/updates a CONCEALED field, matching the other
# secrets on this item (CLAUDE_CODE_OAUTH_TOKEN etc.).
op item edit "$ITEM" --vault "$VAULT" "${FIELD}[password]=${value}" >/dev/null

# Verify by length, never by value.
stored_len="$(op item get "$ITEM" --vault "$VAULT" --fields "label=$FIELD" --reveal 2>/dev/null | wc -c | tr -d ' ')"
if [ "$stored_len" -lt 100 ]; then
  echo "error: field written but reads back as only ${stored_len} bytes - check it manually." >&2
  exit 1
fi

echo "OK: $FIELD stored (${stored_len} bytes read back)"
echo
echo "Next:"
echo "  just dev-down && just dev     # picks it up via op_env_export.py"
echo "  docker exec syn-api sh -c '[ -n \"\$CODEX_AUTH_JSON\" ] && echo present'"
