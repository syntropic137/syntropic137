"""Seed example workflows into the event store.

Standalone dev script — loads YAML definitions from workflows/examples/
and creates them via the domain's WorkflowSeeder. Called by `just seed-workflows`.

Usage:
    uv run python scripts/seed_workflows.py [--dir DIR] [--file FILE] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKFLOWS_DIR = REPO_ROOT / "workflows" / "examples"


async def _seed(
    directory: Path,
    file: Path | None,
    dry_run: bool,
) -> int:
    from aef_adapters.storage import (
        connect_event_store,
        disconnect_event_store,
        get_event_publisher,
        get_workflow_repository,
    )
    from aef_domain.contexts.orchestration.seed_workflow import WorkflowSeeder
    from aef_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

    await connect_event_store()

    try:
        handler = CreateWorkflowTemplateHandler(
            repository=get_workflow_repository(),
            event_publisher=get_event_publisher(),
        )
        seeder = WorkflowSeeder(handler)

        if dry_run:
            print("DRY RUN — no workflows will be created\n")

        if file:
            if not file.exists():
                print(f"File not found: {file}", file=sys.stderr)
                return 1
            print(f"Seeding from file: {file}")
            result = await seeder.seed_from_file(file, dry_run=dry_run)
            _print_result(result)
            return 0 if result.success else 1

        if not directory.exists():
            print(f"Directory not found: {directory}", file=sys.stderr)
            return 1

        print(f"Seeding from directory: {directory}\n")
        report = await seeder.seed_from_directory(directory, dry_run=dry_run)

        for r in report.results:
            _print_result(r)

        print(
            f"\nTotal: {report.total}  Succeeded: {report.succeeded}  "
            f"Skipped: {report.skipped}  Failed: {report.failed}"
        )
        return 1 if report.failed > 0 else 0
    finally:
        await disconnect_event_store()


def _print_result(result) -> None:
    if result.success:
        print(f"  ✓ {result.name} ({result.workflow_id[:12]}...)")
    elif result.error and "already exists" in result.error:
        print(f"  ○ {result.name} (skipped — already exists)")
    else:
        print(f"  ✗ {result.name}: {result.error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed workflows from YAML definitions")
    parser.add_argument(
        "--dir",
        "-d",
        type=Path,
        default=DEFAULT_WORKFLOWS_DIR,
        help=f"Directory containing YAML files (default: {DEFAULT_WORKFLOWS_DIR})",
    )
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        default=None,
        help="Single YAML file to seed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without creating workflows",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(_seed(args.dir, args.file, args.dry_run))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
