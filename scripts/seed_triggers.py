"""Seed trigger presets into the event store.

Standalone dev script — first seeds trigger-associated workflows from
workflows/triggers/, then registers built-in trigger presets (self-healing,
review-fix, comment-command) for target repositories via syn_api.

Called by `just seed-triggers`.

Usage:
    uv run python scripts/seed_triggers.py [--repository OWNER/REPO ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIGGER_WORKFLOWS_DIR = REPO_ROOT / "workflows" / "triggers"

DEFAULT_REPOSITORIES = [
    "syntropic137/agentic-engineering-framework",
    "syntropic137/sandbox_syn-engineer-beta",
]


async def _seed_trigger_workflows(dry_run: bool) -> bool:
    """Seed workflow templates that triggers depend on.

    Returns True if all workflows seeded successfully (or already exist).
    """
    from syn_adapters.storage import (
        get_event_publisher,
        get_workflow_repository,
    )
    from syn_domain.contexts.orchestration.seed_workflow import WorkflowSeeder
    from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

    if not TRIGGER_WORKFLOWS_DIR.exists():
        print(f"  ⚠ Trigger workflows directory not found: {TRIGGER_WORKFLOWS_DIR}")
        return False

    handler = CreateWorkflowTemplateHandler(
        repository=get_workflow_repository(),
        event_publisher=get_event_publisher(),
    )
    seeder = WorkflowSeeder(handler)

    # Pre-load existing IDs so the seeder skips them without hitting the event store.
    # This prevents noisy gRPC ABORTED errors from optimistic concurrency checks.
    from syn_adapters.projection_stores import get_projection_store

    store = get_projection_store()
    existing = await store.get_all("workflow_summaries")
    seeder.register_existing({w["id"] for w in existing if "id" in w})

    report = await seeder.seed_from_directory(TRIGGER_WORKFLOWS_DIR, dry_run=dry_run)

    for r in report.results:
        if r.success:
            print(f"    ✓ {r.name} ({r.workflow_id[:12]}...)")
        elif r.error and "already exists" in r.error:
            print(f"    ○ {r.name} (skipped — already exists)")
        else:
            print(f"    ✗ {r.name}: {r.error}")

    return report.failed == 0


async def _seed(repositories: list[str], dry_run: bool) -> int:
    from syn_domain.contexts.github._shared.trigger_presets import PRESETS

    if dry_run:
        print("DRY RUN — no triggers will be created\n")
        print("  Trigger workflows:")
        await _seed_trigger_workflows(dry_run=True)
        print()
        for repo in repositories:
            for name in PRESETS:
                print(f"  ○ {name} → {repo}")
        print(f"\nTotal: {len(PRESETS) * len(repositories)}  (dry run)")
        return 0

    import syn_api.v1.triggers as tr
    from syn_api._wiring import ensure_connected
    from syn_api.types import Err, Ok

    await ensure_connected()

    # Step 1: Seed the workflows that triggers reference
    print("  Seeding trigger workflows...")
    workflows_ok = await _seed_trigger_workflows(dry_run=False)
    if not workflows_ok:
        print("\n  ✗ Failed to seed trigger workflows — aborting trigger creation")
        return 1
    print()

    # Step 2: Seed the trigger presets
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
