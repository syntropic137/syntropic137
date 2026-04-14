"""Offline demo data seeding — creates workflow templates and trigger presets."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from syn_api._wiring import (
    ensure_connected,
    get_trigger_repo,
    get_trigger_store,
    get_workflow_repo,
    sync_published_events_to_projections,
)

logger = logging.getLogger(__name__)


async def seed_offline_data() -> None:
    """Seed demo data for offline development mode.

    Creates workflow templates and trigger presets so the dashboard
    renders meaningful content without any external services.
    """
    await ensure_connected()

    workflows_seeded = await _seed_workflow_templates()
    triggers_seeded = await _seed_trigger_presets()

    await sync_published_events_to_projections()

    logger.info(
        "Offline mode: seeded %d workflows, %d triggers",
        workflows_seeded,
        triggers_seeded,
    )


async def _seed_workflow_templates() -> int:
    """Seed workflow templates, returning the count of newly created ones."""
    from syn_adapters.storage import get_event_publisher, get_workflow_repository
    from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

    handler = CreateWorkflowTemplateHandler(
        repository=get_workflow_repository(),
        event_publisher=get_event_publisher(),
    )

    count = 0
    for wf_def in _OFFLINE_WORKFLOW_DEFS:
        try:
            from syn_domain.contexts.orchestration import CreateWorkflowTemplateCommand

            command = CreateWorkflowTemplateCommand(**wf_def)
            await handler.handle(command)
            count += 1
        except Exception:
            logger.debug("Skipped seeding workflow '%s' (may already exist)", wf_def["name"])

    return count


async def _seed_trigger_presets() -> int:
    """Seed trigger presets by calling domain handlers directly.

    Mirrors the logic in routes/triggers/commands.py:enable_preset
    without the cross-layer dependency on the route module.
    """
    from syn_domain.contexts.github import RegisterTriggerHandler, create_preset_command

    store = get_trigger_store()
    repo = get_trigger_repo()
    workflow_repo = get_workflow_repo()
    handler = RegisterTriggerHandler(store=store, repository=repo)

    count = 0
    for preset_name in ("self-healing", "review-fix"):
        try:
            command = create_preset_command(
                preset_name=preset_name,
                repository="demo/offline-repo",
                installation_id="",
                created_by="offline-seed",
            )
            # Skip if workflow template doesn't exist yet
            if not await workflow_repo.exists(command.workflow_id):
                logger.debug("Skipped trigger preset '%s' — workflow not found", preset_name)
                continue

            aggregate = await handler.handle(command)
            await store.index_trigger(
                trigger_id=aggregate.trigger_id,
                name=aggregate.name,
                event=aggregate.event,
                repository=aggregate.repository,
                workflow_id=aggregate.workflow_id,
                conditions=[
                    {"field": c.field, "operator": c.operator, "value": c.value}
                    for c in aggregate.conditions
                ],
                input_mapping=aggregate.input_mapping,
                config=aggregate.config,
                installation_id=aggregate.installation_id,
                created_by=aggregate.created_by,
                status=aggregate.status.value,
                created_at=datetime.now(UTC),
            )
            count += 1
        except Exception:
            logger.debug("Skipped seeding trigger preset '%s'", preset_name)

    return count


# Seed data consumed via **kwargs by Pydantic CreateWorkflowTemplateCommand
_OFFLINE_WORKFLOW_DEFS: list[dict] = [
    {
        "aggregate_id": "self-heal-pr",
        "name": "Self-Heal PR",
        "description": "Automatically fix failing CI checks by analyzing logs and applying patches.",
        "workflow_type": "implementation",
        "classification": "standard",
        "repository_url": "https://github.com/demo/offline-repo",
        "phases": [
            {
                "phase_id": "diagnose",
                "name": "diagnose",
                "order": 1,
                "description": "Analyze CI failure logs and identify root cause",
                "prompt_template": "Analyze the following CI failure and identify the root cause:\n{ci_logs}",
            },
            {
                "phase_id": "fix",
                "name": "fix",
                "order": 2,
                "description": "Apply automated fix based on diagnosis",
                "prompt_template": "Apply a fix for the diagnosed issue:\n{diagnosis}",
            },
        ],
    },
    {
        "aggregate_id": "documentation-sync",
        "name": "Documentation Sync",
        "description": "Keep documentation in sync with code changes.",
        "workflow_type": "custom",
        "classification": "simple",
        "repository_url": "https://github.com/demo/offline-repo",
        "phases": [
            {
                "phase_id": "detect",
                "name": "detect",
                "order": 1,
                "description": "Detect documentation that needs updating",
                "prompt_template": "Identify documentation that needs updating based on:\n{changes}",
            },
        ],
    },
]
