"""Transparent 1Password secret resolution via a single vault item.

At startup, derives the vault name from ``APP_ENVIRONMENT`` (no separate
``OP_VAULT`` variable needed), fetches all fields from the
``syntropic137-config`` item and injects them into os.environ before pydantic
reads them. One ``op item get`` call — no per-field round trips.

Usage:
    resolve_op_secrets()  # call before Settings() is constructed
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from syn_shared.settings.env_file import parse_env_file
from syn_shared.settings.op_client import fetch_op_item, inject_fields, op_available

logger = logging.getLogger(__name__)

# Name of the 1Password item that holds all secrets (one per vault).
_OP_ITEM_TITLE = "syntropic137-config"

# Canonical mapping: APP_ENVIRONMENT → vault name.
_ENV_TO_VAULT: dict[str, str] = {
    "selfhost": "syntropic137",
    "development": "syn137-dev",
    "beta": "syn137-beta",
    "staging": "syn137-staging",
    "production": "syn137-prod",
}

# Environments that skip 1Password resolution entirely.
_SKIP_ENVIRONMENTS: frozenset[str] = frozenset({"test", "offline"})

# Prefix for per-vault service account token env vars.
_OP_SAT_PREFIX = "OP_SERVICE_ACCOUNT_TOKEN_"


def vault_name_for_env(app_env: str) -> str:
    """Return the 1Password vault name for a given APP_ENVIRONMENT value."""
    try:
        return _ENV_TO_VAULT[app_env]
    except KeyError:
        allowed = ", ".join(sorted(_ENV_TO_VAULT))
        raise ValueError(
            f"No vault mapping for APP_ENVIRONMENT={app_env!r}. Known environments: {allowed}"
        ) from None


@lru_cache(maxsize=1)
def resolve_op_secrets(env_file: str = ".env") -> None:
    """Fetch all fields from the syntropic137-config item and inject into os.environ.

    Runs exactly once per process (lru_cache). Safe to call multiple times.
    """
    candidates = parse_env_file(Path(env_file))
    candidates.update(os.environ)

    app_env = candidates.get("APP_ENVIRONMENT", "").strip().lower()
    if not app_env or app_env in _SKIP_ENVIRONMENTS or app_env not in _ENV_TO_VAULT:
        logger.debug("APP_ENVIRONMENT=%r — skipping 1Password resolution", app_env or "(not set)")
        return

    op_vault = _ENV_TO_VAULT[app_env]

    # Inject vault-specific service account token before checking op availability.
    vault_sat_key = _OP_SAT_PREFIX + op_vault.upper().replace("-", "_")
    vault_sat = candidates.get(vault_sat_key, "").strip()
    if vault_sat:
        os.environ["OP_SERVICE_ACCOUNT_TOKEN"] = vault_sat
        logger.debug("Using vault-specific service account token (%s)", vault_sat_key)

    if not op_available():
        return

    logger.debug("Fetching secrets from op://%s/%s", op_vault, _OP_ITEM_TITLE)

    item = fetch_op_item(op_vault, _OP_ITEM_TITLE)
    if item is None:
        return

    injected = inject_fields(item)
    logger.debug("Injected %d secret(s) from 1Password", injected)


def reset_op_resolver() -> None:
    """Clear the op resolver cache (for testing)."""
    resolve_op_secrets.cache_clear()
