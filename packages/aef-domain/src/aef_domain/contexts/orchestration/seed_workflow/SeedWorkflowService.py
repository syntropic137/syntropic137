"""Service for seeding workflows from YAML definitions.

This service handles the process of loading workflow YAML files
and creating corresponding workflows in the event store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 - needed at runtime for file operations
from typing import TYPE_CHECKING

from aef_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
    load_workflow_definitions,
)
from aef_domain.contexts.orchestration.domain.commands.CreateWorkflowCommand import (
    CreateWorkflowCommand,
)
from aef_shared.logging import get_logger

if TYPE_CHECKING:
    from aef_domain.contexts.orchestration.slices.create_workflow.CreateWorkflowHandler import (
        CreateWorkflowHandler,
    )

logger = get_logger(__name__)


@dataclass
class SeedResult:
    """Result of a workflow seeding operation."""

    workflow_id: str
    name: str
    success: bool
    error: str | None = None


@dataclass
class SeedReport:
    """Report of a complete seeding operation."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[SeedResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        """Check if all workflows were seeded successfully."""
        return self.failed == 0 and self.succeeded > 0


class WorkflowSeeder:
    """Service for seeding workflows from YAML definitions."""

    def __init__(
        self,
        handler: CreateWorkflowHandler,
        *,
        skip_existing: bool = True,
    ) -> None:
        """Initialize the seeder.

        Args:
            handler: The CreateWorkflowHandler to use for creating workflows.
            skip_existing: If True, skip workflows that already exist.
        """
        self._handler = handler
        self._skip_existing = skip_existing
        self._existing_ids: set[str] = set()

    async def seed_from_directory(
        self,
        directory: Path,
        *,
        dry_run: bool = False,
    ) -> SeedReport:
        """Seed all workflows from a directory.

        Args:
            directory: Path to directory containing YAML files.
            dry_run: If True, validate but don't actually create workflows.

        Returns:
            SeedReport with results of the operation.
        """
        logger.info(
            "Starting workflow seeding",
            directory=str(directory),
            dry_run=dry_run,
        )

        definitions = load_workflow_definitions(directory)
        report = SeedReport(total=len(definitions))

        for definition in definitions:
            result = await self._seed_workflow(definition, dry_run=dry_run)
            report.results.append(result)

            if result.success:
                report.succeeded += 1
            elif result.error and "already exists" in result.error:
                report.skipped += 1
            else:
                report.failed += 1

        logger.info(
            "Workflow seeding complete",
            total=report.total,
            succeeded=report.succeeded,
            failed=report.failed,
            skipped=report.skipped,
        )

        return report

    async def seed_from_file(
        self,
        file_path: Path,
        *,
        dry_run: bool = False,
    ) -> SeedResult:
        """Seed a single workflow from a YAML file.

        Args:
            file_path: Path to the YAML file.
            dry_run: If True, validate but don't actually create.

        Returns:
            SeedResult for the operation.
        """
        logger.info("Seeding workflow from file", file=str(file_path))
        definition = WorkflowDefinition.from_file(file_path)
        return await self._seed_workflow(definition, dry_run=dry_run)

    async def _seed_workflow(
        self,
        definition: WorkflowDefinition,
        *,
        dry_run: bool = False,
    ) -> SeedResult:
        """Seed a single workflow from a definition.

        Args:
            definition: The parsed workflow definition.
            dry_run: If True, validate but don't actually create.

        Returns:
            SeedResult for the operation.
        """
        workflow_id = definition.id

        # Check if already exists (when skip_existing is enabled)
        if self._skip_existing and workflow_id in self._existing_ids:
            logger.debug(
                "Skipping existing workflow",
                workflow_id=workflow_id,
            )
            return SeedResult(
                workflow_id=workflow_id,
                name=definition.name,
                success=False,
                error=f"Workflow {workflow_id} already exists",
            )

        if dry_run:
            logger.info(
                "Dry-run: would create workflow",
                workflow_id=workflow_id,
                name=definition.name,
                phases=len(definition.phases),
            )
            return SeedResult(
                workflow_id=workflow_id,
                name=definition.name,
                success=True,
            )

        # Build the command - use placeholder URL if no repository configured
        default_url = "https://github.com/placeholder/not-configured"
        command = CreateWorkflowCommand(
            aggregate_id=workflow_id,
            name=definition.name,
            workflow_type=definition.type,
            classification=definition.classification,
            repository_url=(definition.repository.url if definition.repository else default_url),
            repository_ref=(definition.repository.ref if definition.repository else "main"),
            phases=definition.get_domain_phases(),
            project_name=definition.project_name,
            description=definition.description,
        )

        try:
            created_id = await self._handler.handle(command)
            self._existing_ids.add(workflow_id)

            logger.info(
                "Workflow seeded successfully",
                workflow_id=created_id,
                name=definition.name,
            )

            return SeedResult(
                workflow_id=created_id,
                name=definition.name,
                success=True,
            )
        except Exception as e:
            error_str = str(e)
            # Check for concurrency/duplicate errors (workflow already exists)
            is_duplicate = any(
                msg in error_str.lower()
                for msg in [
                    "already exists",
                    "precondition failed",
                    "concurrency conflict",
                    "duplicate",
                ]
            )

            if is_duplicate:
                self._existing_ids.add(workflow_id)
                logger.info(
                    "Workflow already exists, skipping",
                    workflow_id=workflow_id,
                    name=definition.name,
                )
                return SeedResult(
                    workflow_id=workflow_id,
                    name=definition.name,
                    success=False,
                    error=f"Workflow {workflow_id} already exists",
                )

            logger.error(
                "Failed to seed workflow",
                workflow_id=workflow_id,
                error=error_str,
            )
            return SeedResult(
                workflow_id=workflow_id,
                name=definition.name,
                success=False,
                error=error_str,
            )

    def register_existing(self, workflow_ids: set[str]) -> None:
        """Register existing workflow IDs to skip during seeding.

        Args:
            workflow_ids: Set of workflow IDs that already exist.
        """
        self._existing_ids.update(workflow_ids)
