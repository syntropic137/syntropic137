"""Seed trigger presets into the event store.

Standalone dev script — registers built-in trigger presets (self-healing,
review-fix) for target repositories via aef_api. Called by `just seed-triggers`.

Usage:
    uv run python scripts/seed_triggers.py [--repository OWNER/REPO ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

DEFAULT_REPOSITORIES = [
    "AgentParadise/agentic-engineering-framework",
    "AgentParadise/sandbox_aef-engineer-beta",
]


async def _seed(repositories: list[str], dry_run: bool) -> int:
    from aef_domain.contexts.github._shared.trigger_presets import PRESETS

    if dry_run:
        print("DRY RUN — no triggers will be created\n")
        for repo in repositories:
            for name in PRESETS:
                print(f"  ○ {name} → {repo}")
        print(f"\nTotal: {len(PRESETS) * len(repositories)}  (dry run)")
        return 0

    import aef_api.v1.triggers as tr
    from aef_api._wiring import ensure_connected
    from aef_api.types import Err, Ok

    await ensure_connected()

    succeeded = 0
    skipped = 0
    failed = 0

    for repo in repositories:
        print(f"  [{repo}]")
        for preset_name in PRESETS:
            result = await tr.enable_preset(
                preset_name=preset_name,
                repository=repo,
                installation_id="",
                created_by="seed-script",
            )
            match result:
                case Ok(trigger_id):
                    print(f"    ✓ {preset_name} ({trigger_id[:12]}...)")
                    succeeded += 1
                case Err(_, message=msg) if msg and "already exists" in msg.lower():
                    print(f"    ○ {preset_name} (skipped — already exists)")
                    skipped += 1
                case Err(_, message=msg):
                    print(f"    ✗ {preset_name}: {msg}")
                    failed += 1

    total = len(PRESETS) * len(repositories)
    print(f"\nTotal: {total}  Succeeded: {succeeded}  Skipped: {skipped}  Failed: {failed}")
    return 1 if failed > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed trigger presets")
    parser.add_argument(
        "--repository",
        "-r",
        type=str,
        action="append",
        dest="repositories",
        help="Target repository (repeatable, defaults to built-in list)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be seeded without creating triggers",
    )
    args = parser.parse_args()

    repositories = args.repositories or DEFAULT_REPOSITORIES

    print(f"Seeding trigger presets for: {', '.join(repositories)}\n")

    exit_code = asyncio.run(_seed(repositories, args.dry_run))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
