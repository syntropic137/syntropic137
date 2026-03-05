"""Transparent 1Password secret resolution via a single vault item.

At startup, derives the vault name from ``APP_ENVIRONMENT`` (no separate
``OP_VAULT`` variable needed), fetches all fields from the
``syntropic137-config`` item and injects them into os.environ before pydantic
reads them. One ``op item get`` call — no per-field round trips.

Usage:
    resolve_op_secrets()  # call before Settings() is constructed

Requirements:
    - ``op`` CLI in PATH
    - ``APP_ENVIRONMENT`` set in .env or shell (development, beta, staging, production)
    - One of: OP_SERVICE_ACCOUNT_TOKEN, OP_SESSION, or interactive sign-in
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Name of the 1Password item that holds all secrets (one per vault).
_OP_ITEM_TITLE = "syntropic137-config"

# Canonical mapping: APP_ENVIRONMENT → vault name.
# The vault name is deterministically derived from the environment — no separate
# OP_VAULT variable needed. This eliminates an entire class of mismatch errors.
_ENV_TO_VAULT: dict[str, str] = {
    "development": "syn137-dev",
    "beta": "syn137-beta",
    "staging": "syn137-staging",
    "production": "syn137-prod",
}

# Environments that skip 1Password resolution entirely (no vault exists).
_SKIP_ENVIRONMENTS: frozenset[str] = frozenset({"test", "offline"})

# Prefix for per-vault service account token env vars.
# e.g. syn137-dev  → OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV
# e.g. syn137-prod → OP_SERVICE_ACCOUNT_TOKEN_SYN137_PROD
_OP_SAT_PREFIX = "OP_SERVICE_ACCOUNT_TOKEN_"


def _op_available() -> bool:
    """Return True if `op` CLI is installed and authenticated."""
    if not shutil.which("op"):
        return False

    # Service account token or session token satisfies auth without a subprocess call
    if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN") or os.environ.get("OP_SESSION"):
        return True

    # Fall back to an interactive check — fails fast if not signed in
    try:
        result = subprocess.run(
            ["op", "whoami"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a key→value dict."""
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            result[key] = value

    return result


def vault_name_for_env(app_env: str) -> str:
    """Return the 1Password vault name for a given APP_ENVIRONMENT value.

    Args:
        app_env: The environment string (e.g. "development", "production").

    Returns:
        The vault name (e.g. "syn137-dev", "syn137-prod").

    Raises:
        ValueError: If *app_env* has no known vault mapping.
    """
    try:
        return _ENV_TO_VAULT[app_env]
    except KeyError:
        allowed = ", ".join(sorted(_ENV_TO_VAULT))
        raise ValueError(
            f"No vault mapping for APP_ENVIRONMENT={app_env!r}. "
            f"Known environments: {allowed}"
        ) from None


@lru_cache(maxsize=1)
def resolve_op_secrets(env_file: str = ".env") -> None:
    """Fetch all fields from the syntropic137-config item and inject into os.environ.

    Runs exactly once per process (lru_cache). Safe to call multiple times.

    Steps:
    1. Read APP_ENVIRONMENT from .env / os.environ
    2. Derive vault name via ``vault_name_for_env()``
    3. Fetch the entire item via ``op item get --format json`` (one call)
    4. Inject each field label→value into os.environ
    5. Existing env vars are never overwritten

    Args:
        env_file: Path to the .env file to read APP_ENVIRONMENT from (default ".env").
    """
    candidates = _parse_env_file(Path(env_file))
    candidates.update(os.environ)

    app_env = candidates.get("APP_ENVIRONMENT", "").strip().lower()
    if not app_env:
        logger.debug("APP_ENVIRONMENT not set — skipping 1Password resolution")
        return

    if app_env in _SKIP_ENVIRONMENTS:
        logger.debug("APP_ENVIRONMENT=%s — skipping 1Password resolution", app_env)
        return

    if app_env not in _ENV_TO_VAULT:
        logger.debug("APP_ENVIRONMENT=%s has no vault mapping — skipping", app_env)
        return

    op_vault = _ENV_TO_VAULT[app_env]

    # Inject vault-specific service account token before checking op availability.
    # OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV always takes precedence over the generic
    # OP_SERVICE_ACCOUNT_TOKEN — prevents a stale generic token from shadowing the
    # correct vault-specific one.
    vault_sat_key = _OP_SAT_PREFIX + op_vault.upper().replace("-", "_")
    vault_sat = candidates.get(vault_sat_key, "").strip()
    if vault_sat:
        os.environ["OP_SERVICE_ACCOUNT_TOKEN"] = vault_sat
        logger.debug("Using vault-specific service account token (%s)", vault_sat_key)

    if not _op_available():
        return

    logger.debug("Fetching secrets from op://%s/%s", op_vault, _OP_ITEM_TITLE)

    try:
        result = subprocess.run(
            ["op", "item", "get", _OP_ITEM_TITLE, "--vault", op_vault, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timed out fetching 1Password item %s", _OP_ITEM_TITLE)
        return
    except OSError as exc:
        logger.warning("Error fetching 1Password item %s: %s", _OP_ITEM_TITLE, exc)
        return

    if result.returncode != 0:
        logger.warning(
            "Failed to fetch 1Password item %s from vault %s: %s",
            _OP_ITEM_TITLE,
            op_vault,
            result.stderr.strip(),
        )
        return

    try:
        item = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse 1Password item response: %s", exc)
        return

    injected = 0
    for field in item.get("fields", []):
        label = field.get("label", "").strip()
        value = field.get("value", "")
        if label and value and not os.environ.get(label):
            os.environ[label] = value
            injected += 1

    logger.debug("Injected %d secret(s) from 1Password", injected)


def reset_op_resolver() -> None:
    """Clear the op resolver cache (for testing)."""
    resolve_op_secrets.cache_clear()
