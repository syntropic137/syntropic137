"""Print KEY='VALUE' lines for infra env vars + 1Password secrets.

Called by justfile recipes that need infra/.env variables (selfhost,
webhooks, etc.). The root .env is loaded by justfile's native
`set dotenv-load` - this script handles the rest.

Usage in justfile:
    eval "$(uv run python scripts/resolve_infra_env.py)"

See ADR-004: Environment Configuration with Pydantic Settings.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

INFRA_ENV = Path("infra/.env")

# Migration: SYN_DOMAIN -> SYN_PUBLIC_HOSTNAME (remove after v0.24)
_DEPRECATED_SYN_DOMAIN = "SYN_DOMAIN"
_NEW_SYN_PUBLIC_HOSTNAME = "SYN_PUBLIC_HOSTNAME"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into key-value pairs."""
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
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def main() -> None:
    # 1. Load infra/.env
    env_vars = _parse_env_file(INFRA_ENV) if INFRA_ENV.exists() else {}
    for key, value in env_vars.items():
        # Shell-safe output for eval
        safe_value = value.replace("'", "'\\''")
        print(f"{key}='{safe_value}'")

    # 2. Backwards-compat bridge: SYN_DOMAIN -> SYN_PUBLIC_HOSTNAME
    # Check both os.environ and parsed env_vars so the bridge works
    # regardless of whether SYN_DOMAIN is set in the shell or in infra/.env.
    old_val = os.environ.get(_DEPRECATED_SYN_DOMAIN, "") or env_vars.get(_DEPRECATED_SYN_DOMAIN, "")
    new_val = os.environ.get(_NEW_SYN_PUBLIC_HOSTNAME, "") or env_vars.get(_NEW_SYN_PUBLIC_HOSTNAME, "")
    if old_val and not new_val:
        safe_val = old_val.replace("'", "'\\''")
        print(f"{_NEW_SYN_PUBLIC_HOSTNAME}='{safe_val}'")
        print(
            f"WARNING: {_DEPRECATED_SYN_DOMAIN} is deprecated. "
            f"Rename to {_NEW_SYN_PUBLIC_HOSTNAME} in your .env",
            file=sys.stderr,
        )

    # 3. Resolve 1Password secrets for known environments
    app_env = os.environ.get("APP_ENVIRONMENT", "").strip().lower()
    if app_env in ("development", "production", "beta", "staging"):
        try:
            result = subprocess.run(
                ["uv", "run", "python", "scripts/op_env_export.py"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                print(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass


if __name__ == "__main__":
    main()
