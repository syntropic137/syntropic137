# See ADR-066: this seeder is a dev/CI tool that lives in the domain package
# but is invoked from scripts; it never runs inside the request lifecycle. After
# the #726 Phase A redesign, the resolver call here is pure validation -- it
# refuses to seed any workflow that references an unregistered plugin (the CLI
# must register plugins first via POST /claude-plugins/registrations).
"""Service for seeding workflows from YAML definitions.

**Development / testing tool only.** This service bypasses the HTTP API
and writes directly to the event store via ``CreateWorkflowTemplateHandler``.
It exists so developers and CI can bootstrap example workflows quickly
(e.g. ``just seed-workflows``).

For production user-facing installation, use the CLI command
``syn workflow install`` which resolves packages client-side and
POSTs the resolved workflow(s) through the public API.

During seeding, ``prompt_file`` references in phase definitions are
resolved to their ``.md`` file contents (frontmatter merged, body
becomes ``prompt_template``) via ``WorkflowDefinition.from_file()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 - needed at runtime for file operations
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginError,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
    load_workflow_definitions,
)
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_shared.logging import get_logger

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )


class _ClaudePluginResolver(Protocol):
    """Minimal contract the seeder needs from the resolution service.

    Defined locally so the domain layer never imports the API service module
    (would invert the dependency direction). Production wires
    ``ClaudePluginResolutionService`` here; tests pass a no-op or a stub.
    """

    async def ensure_registered(self, workflow_def: WorkflowDefinition) -> None: ...


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


_DUPLICATE_MARKERS = ("already exists", "precondition failed", "concurrency conflict", "duplicate")


def _handle_seed_error(
    error: Exception,
    workflow_id: str,
    name: str,
    existing_ids: set[str],
) -> SeedResult:
    """Handle seeding error, distinguishing duplicates from real failures."""
    error_str = str(error)
    is_duplicate = any(msg in error_str.lower() for msg in _DUPLICATE_MARKERS)
    if is_duplicate:
        existing_ids.add(workflow_id)
        logger.info("Workflow already exists, skipping", workflow_id=workflow_id, name=name)
        return SeedResult(
            workflow_id=workflow_id,
            name=name,
            success=False,
            error=f"Workflow {workflow_id} already exists",
        )
    logger.error("Failed to seed workflow", workflow_id=workflow_id, error=error_str)
    return SeedResult(workflow_id=workflow_id, name=name, success=False, error=error_str)


class WorkflowSeeder:
    """Development-only service for seeding workflows directly into the event store.

    Bypasses the HTTP API — intended for ``just seed-workflows``, test fixtures,
    and local development bootstrapping. Production workflow installation goes
    through ``syn workflow install`` → API.
    """

    def __init__(
        self,
        handler: CreateWorkflowTemplateHandler,
        *,
        skip_existing: bool = True,
        claude_plugin_resolver: _ClaudePluginResolver | None = None,
        fail_on_plugin_not_registered: bool = True,
    ) -> None:
        """Initialize the seeder.

        Args:
            handler: The CreateWorkflowTemplateHandler to use for creating workflows.
            skip_existing: If True, skip workflows that already exist.
            claude_plugin_resolver: Optional resolver for ``claude_plugins`` refs
                (issue #726). When provided, every YAML's plugin refs are
                validated against the lock projection before the workflow is
                registered. When ``None``, plugin validation is skipped entirely
                -- safe for legacy seed paths that pre-date #726.
            fail_on_plugin_not_registered: When True (production default), a
                missing plugin registration aborts the seeder by re-raising.
                When False (dev/CI), the failure is logged and the workflow is
                recorded as failed but seeding continues.
        """
        self._handler = handler
        self._skip_existing = skip_existing
        self._existing_ids: set[str] = set()
        self._claude_plugin_resolver = claude_plugin_resolver
        self._fail_on_plugin_not_registered = fail_on_plugin_not_registered

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
        """Seed a single workflow from a definition."""
        workflow_id = definition.id

        skip_result = self._skip_if_existing(definition)
        if skip_result is not None:
            return skip_result

        if dry_run:
            return self._dry_run_result(definition)

        plugin_failure = await self._validate_plugins(definition)
        if plugin_failure is not None:
            return plugin_failure

        return await self._dispatch_create(definition, workflow_id)

    def _skip_if_existing(self, definition: WorkflowDefinition) -> SeedResult | None:
        workflow_id = definition.id
        if not (self._skip_existing and workflow_id in self._existing_ids):
            return None
        logger.debug("Skipping existing workflow", workflow_id=workflow_id)
        return SeedResult(
            workflow_id=workflow_id,
            name=definition.name,
            success=False,
            error=f"Workflow {workflow_id} already exists",
        )

    def _dry_run_result(self, definition: WorkflowDefinition) -> SeedResult:
        logger.info(
            "Dry-run: would create workflow",
            workflow_id=definition.id,
            name=definition.name,
            phases=len(definition.phases),
        )
        return SeedResult(workflow_id=definition.id, name=definition.name, success=True)

    async def _validate_plugins(self, definition: WorkflowDefinition) -> SeedResult | None:
        """Validate claude plugin refs against the lock projection (#726 Phase A).

        Returns ``None`` on success (caller continues), a failure ``SeedResult``
        when dev/CI mode tolerates the miss, or re-raises in prod mode.
        """
        if self._claude_plugin_resolver is None:
            return None
        try:
            await self._claude_plugin_resolver.ensure_registered(definition)
        except ClaudePluginError as exc:
            if self._fail_on_plugin_not_registered:
                raise
            logger.error(
                "Skipping workflow seed: claude plugin not registered",
                workflow_id=definition.id,
                name=definition.name,
                error_code=exc.error_code,
                error=str(exc),
            )
            return SeedResult(
                workflow_id=definition.id,
                name=definition.name,
                success=False,
                error=f"claude_plugin_not_registered: {exc}",
            )
        return None

    async def _dispatch_create(
        self,
        definition: WorkflowDefinition,
        workflow_id: str,
    ) -> SeedResult:
        command = build_command_from_definition(definition)
        try:
            created_id = await self._handler.handle(command)
        except Exception as e:
            return _handle_seed_error(e, workflow_id, definition.name, self._existing_ids)
        self._existing_ids.add(workflow_id)
        logger.info("Workflow seeded successfully", workflow_id=created_id, name=definition.name)
        return SeedResult(workflow_id=created_id, name=definition.name, success=True)

    def register_existing(self, workflow_ids: set[str]) -> None:
        """Register existing workflow IDs to skip during seeding.

        Args:
            workflow_ids: Set of workflow IDs that already exist.
        """
        self._existing_ids.update(workflow_ids)
