"""Manage GitHub App webhook URL for dev/prod switching.

Automatically switches the GitHub App's webhook URL between Smee.io (local dev)
and Cloudflare Tunnel (production). Called by `just dev` / `just dev-stop`.

Usage:
    uv run python scripts/manage_webhook_url.py --mode dev      # Switch to Smee
    uv run python scripts/manage_webhook_url.py --mode prod     # Restore Cloudflare
    uv run python scripts/manage_webhook_url.py --check         # Show current config
    uv run python scripts/manage_webhook_url.py --mode dev --dry-run  # Preview only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Source .env file into os.environ (best-effort)."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _get_smee_url() -> str | None:
    return os.environ.get("DEV__SMEE_URL") or None


def _get_prod_url() -> str | None:
    domain = os.environ.get("AEF_DOMAIN")
    if domain:
        return f"https://api.{domain}/webhooks/github"
    return None


async def _check() -> int:
    """Print current webhook config."""
    from aef_adapters.github.client import GitHubAppClient
    from aef_shared.settings.github import GitHubAppSettings

    settings = GitHubAppSettings()
    if not settings.is_configured:
        print("GitHub App not configured — skipping webhook check")
        return 0

    async with GitHubAppClient(settings) as client:
        config = await client.get_webhook_config()

    print("Current webhook config:")
    print(f"  URL:          {config.get('url', '(not set)')}")
    print(f"  Content-Type: {config.get('content_type', '?')}")
    print(f"  Insecure SSL: {config.get('insecure_ssl', '?')}")
    return 0


async def _switch(mode: str, dry_run: bool) -> int:
    """Switch webhook URL to dev (Smee) or prod (Cloudflare)."""
    from aef_adapters.github.client import GitHubAppClient
    from aef_shared.settings.github import GitHubAppSettings

    settings = GitHubAppSettings()
    if not settings.is_configured:
        print("GitHub App not configured — skipping webhook switch")
        return 0

    if mode == "dev":
        target_url = _get_smee_url()
        if not target_url:
            print("DEV__SMEE_URL not set — skipping webhook switch")
            return 0
        label = "dev (Smee)"
    else:
        target_url = _get_prod_url()
        if not target_url:
            print("AEF_DOMAIN not set — skipping webhook restore")
            return 0
        label = "prod (Cloudflare)"

    async with GitHubAppClient(settings) as client:
        # Check current URL for idempotency
        config = await client.get_webhook_config()
        current_url = config.get("url", "")

        if current_url == target_url:
            print(f"Webhook URL already set to {label}: {target_url}")
            return 0

        if dry_run:
            print(f"Would switch webhook URL to {label}:")
            print(f"  Current: {current_url}")
            print(f"  Target:  {target_url}")
            return 0

        # Include webhook secret if configured
        secret = settings.webhook_secret.get_secret_value() or None

        await client.update_webhook_config(
            url=target_url,
            content_type="json",
            secret=secret,
        )

    print(f"Webhook URL switched to {label}: {target_url}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage GitHub App webhook URL")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--mode",
        choices=["dev", "prod"],
        help="Switch webhook to dev (Smee) or prod (Cloudflare)",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="Show current webhook config (read-only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without making API calls",
    )
    args = parser.parse_args()

    _load_env()

    try:
        if args.check:
            exit_code = asyncio.run(_check())
        else:
            exit_code = asyncio.run(_switch(args.mode, args.dry_run))
    except Exception as e:
        print(f"Warning: webhook URL management failed: {e}", file=sys.stderr)
        exit_code = 0  # Don't block dev workflow

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
