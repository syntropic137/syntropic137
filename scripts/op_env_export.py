"""Resolve 1Password secrets and print KEY='VALUE' export lines for _env-check.

Called by ``just _env-check`` when ``APP_ENVIRONMENT`` maps to a known vault.
Outputs shell-safe KEY='VALUE' lines that can be eval'd into the bash
environment so the env check sees values stored in 1Password, not just .env
plain text.

Unlike op_resolver.py, this script does NOT skip keys already present in
os.environ - its job is to report what is actually in the vault.

See ADR-004: Environment Configuration with Pydantic Settings.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from syn_shared.settings.constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_SYN_PUBLIC_HOSTNAME,
)

# infra_config lives in infra/scripts/ - add to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra" / "scripts"))

from infra_config import (
    ENV_CLOUDFLARE_TUNNEL_TOKEN,
    ENV_GITHUB_APP_ID,
    ENV_GITHUB_APP_NAME,
    ENV_GITHUB_PRIVATE_KEY,
    ENV_GITHUB_WEBHOOK_SECRET,
    ENV_SYN_API_PASSWORD,
    parse_env_file,
)

_OP_ITEM_TITLE = "syntropic137-config"
_OP_SAT_PREFIX = "OP_SERVICE_ACCOUNT_TOKEN_"

# Canonical env-to-vault mapping (mirrored from op_resolver.py).
_ENV_TO_VAULT: dict[str, str] = {
    "selfhost": "syntropic137",
    "development": "syn137-dev",
    "beta": "syn137-beta",
    "staging": "syn137-staging",
    "production": "syn137-prod",
}

# 1Password vault field labels that we resolve. Built from imported constants
# so there's exactly one place each name is defined.
_KEYS = {
    ENV_GITHUB_APP_ID,
    ENV_GITHUB_APP_NAME,
    ENV_GITHUB_PRIVATE_KEY,
    ENV_GITHUB_WEBHOOK_SECRET,
    ENV_CLOUDFLARE_TUNNEL_TOKEN,
    ENV_SYN_PUBLIC_HOSTNAME,
    ENV_ANTHROPIC_API_KEY,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_SYN_API_PASSWORD,
}


def main() -> None:
    env_file = Path(".env")
    candidates = parse_env_file(env_file)
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
