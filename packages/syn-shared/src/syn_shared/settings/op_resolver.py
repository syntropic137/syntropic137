"""Transparent 1Password secret resolution via a single vault item.

At startup, fetches all fields from the `syntropic137-config` item in the
vault specified by `OP_VAULT` and injects them into os.environ before pydantic
reads them. One `op item get` call — no per-field round trips.

Usage:
    resolve_op_secrets()  # call before Settings() is constructed

Requirements:
    - `op` CLI in PATH
    - OP_VAULT set in .env or shell (e.g. syn137-dev, syn137-beta, syn137-prod)
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

# Env var that selects which vault to read from.
_OP_VAULT_ENV_KEY = "OP_VAULT"

# Maps known vault names to the APP_ENVIRONMENT value they should contain.
# Used for boot-time sanity check: prevents prod secrets running in dev and vice versa.
_VAULT_EXPECTED_ENV: dict[str, str] = {
    "syn137-dev": "development",
    "syn137-beta": "beta",
    "syn137-staging": "staging",
    "syn137-prod": "production",
}

# Prefix for per-vault service account token env vars.
# e.g. syn137-dev  → OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV
# e.g. syn137-prod → OP_SERVICE_ACCOUNT_TOKEN_SYN137_PROD
_OP_SAT_PREFIX = "OP_SERVICE_ACCOUNT_TOKEN_"

# Environments that bypass the vault/env mismatch check (test runs, offline dev).
_SKIP_ENV_VALIDATION: frozenset[str] = frozenset({"test", "offline"})


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


@lru_cache(maxsize=1)
def resolve_op_secrets(env_file: str = ".env") -> None:
    """Fetch all fields from the syntropic137-config item and inject into os.environ.

    Runs exactly once per process (lru_cache). Safe to call multiple times.

    Steps:
    1. Read OP_VAULT from .env / os.environ
    2. Fetch the entire item via `op item get --format json` (one call)
    3. Inject each field label→value into os.environ
    4. Existing env vars are never overwritten

    Args:
        env_file: Path to the .env file to read OP_VAULT from (default ".env").
    """
    # Resolve OP_VAULT — os.environ wins over .env file
    candidates = _parse_env_file(Path(env_file))
    candidates.update(os.environ)

    op_vault = candidates.get(_OP_VAULT_ENV_KEY, "").strip()
    if not op_vault:
        logger.debug("OP_VAULT not set — skipping 1Password resolution")
        return

    # Inject vault-specific service account token before checking op availability.
    # OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV takes precedence over the generic token
    # only when the generic token is not already set in the shell environment.
    vault_sat_key = _OP_SAT_PREFIX + op_vault.upper().replace("-", "_")
    vault_sat = candidates.get(vault_sat_key, "").strip()
    if vault_sat and "OP_SERVICE_ACCOUNT_TOKEN" not in os.environ:
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
    _validate_environment_match(op_vault)


def _validate_environment_match(op_vault: str) -> None:
    """Fail fast if APP_ENVIRONMENT doesn't match the selected vault.

    Guards against accidentally running production workloads with dev secrets,
    or injecting production secrets into a dev/staging process.

    The check is skipped when:
    - The vault name is not one of the known vaults (custom/fork vaults)
    - APP_ENVIRONMENT is not set in the environment
    - APP_ENVIRONMENT is 'test' or 'offline' (CI and local-only runs)

    Args:
        op_vault: The vault name that was used to fetch secrets.

    Raises:
        EnvironmentError: If APP_ENVIRONMENT contradicts the vault's expected environment.
    """
    expected = _VAULT_EXPECTED_ENV.get(op_vault)
    if expected is None:
        return  # Unknown vault — skip check (custom deployments, forks)

    actual = os.environ.get("APP_ENVIRONMENT", "").strip().lower()
    if not actual or actual in _SKIP_ENV_VALIDATION:
        return

    if actual != expected:
        raise OSError(
            f"Environment mismatch — refusing to start.\n"
            f"  OP_VAULT='{op_vault}' expects APP_ENVIRONMENT='{expected}'\n"
            f"  but APP_ENVIRONMENT='{actual}'.\n"
            f"  Fix: set OP_VAULT to match your environment, "
            f"or correct APP_ENVIRONMENT in your .env file."
        )


def reset_op_resolver() -> None:
    """Clear the op resolver cache (for testing)."""
    resolve_op_secrets.cache_clear()
