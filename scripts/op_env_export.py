"""Resolve 1Password secrets and print KEY='VALUE' export lines for _env-check.

Called by ``just _env-check`` when ``APP_ENVIRONMENT`` maps to a known vault.
Outputs shell-safe KEY='VALUE' lines that can be eval'd into the bash
environment so the env check sees values stored in 1Password, not just .env
plain text.

Unlike op_resolver.py, this script does NOT skip keys already present in
os.environ — its job is to report what is actually in the vault.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_OP_ITEM_TITLE = "syntropic137-config"
_OP_SAT_PREFIX = "OP_SERVICE_ACCOUNT_TOKEN_"

# Canonical env→vault mapping (mirrored from op_resolver.py — this script is
# standalone and cannot import from syn_shared).
_ENV_TO_VAULT: dict[str, str] = {
    "selfhost": "syntropic137",
    "development": "syn137-dev",
    "beta": "syn137-beta",
    "staging": "syn137-staging",
    "production": "syn137-prod",
}

_KEYS = {
    "SYN_GITHUB_APP_ID",
    "SYN_GITHUB_APP_NAME",
    "SYN_GITHUB_PRIVATE_KEY",
    "SYN_GITHUB_WEBHOOK_SECRET",
    "CLOUDFLARE_TUNNEL_TOKEN",
    "SYN_DOMAIN",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "SYN_API_PASSWORD",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        value = raw_value.strip().strip("'\"")
        if key:
            result[key] = value
    return result


def main() -> None:
    env_file = Path(".env")
    candidates = _parse_env_file(env_file)
    candidates.update(os.environ)

    app_env = candidates.get("APP_ENVIRONMENT", "").strip().lower()
    op_vault = _ENV_TO_VAULT.get(app_env, "")
    if not op_vault:
        sys.exit(0)

    # Vault-specific token always takes precedence over the generic one
    vault_sat_key = _OP_SAT_PREFIX + op_vault.upper().replace("-", "_")
    vault_sat = candidates.get(vault_sat_key, "").strip()
    if vault_sat:
        os.environ["OP_SERVICE_ACCOUNT_TOKEN"] = vault_sat

    if not shutil.which("op"):
        sys.exit(0)

    try:
        result = subprocess.run(
            ["op", "item", "get", _OP_ITEM_TITLE, "--vault", op_vault, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        sys.exit(0)

    if result.returncode != 0:
        sys.exit(0)

    try:
        item = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(0)

    for field in item.get("fields", []):
        label = field.get("label", "").strip()
        value = field.get("value", "")
        if label in _KEYS and value:
            escaped = value.replace("'", "'\"'\"'")
            print(f"{label}='{escaped}'")


if __name__ == "__main__":
    main()
