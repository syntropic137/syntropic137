"""Print formatted access URLs for the selfhost stack.

Reads SYN_PUBLIC_HOSTNAME and SYN_GATEWAY_PORT from env, delegates to
format_access_urls() from infra_config. Used by justfile selfhost-status
and webhook delivery status recipes.

See ADR-004: Environment Configuration with Pydantic Settings.

Usage in justfile:
    uv run python infra/scripts/print_access_urls.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# infra/scripts is on sys.path when run from repo root via uv
sys.path.insert(0, str(Path(__file__).parent))

from infra_config import format_access_urls


def main() -> None:
    hostname = os.environ.get("SYN_PUBLIC_HOSTNAME", "")
    urls = format_access_urls(hostname)

    print(f"   UI:       {urls['ui']}")
    print(f"   API:      {urls['api']}")
    print(f"   API Docs: {urls['api_docs']}")

    if not hostname:
        print("   (Set SYN_PUBLIC_HOSTNAME in .env for external access)")


if __name__ == "__main__":
    main()
