"""A phase memory request above the ceiling never persists, by any install path (okrs-51p.30).

Codex on #2148: the check lived only in the API's dict mapping, and YAML install
builds its command with ``build_command_from_definition``, so a 12288 MB request
was stored under a 4096 cap. Every install and update path goes through
``CreateWorkflowTemplateHandler``, so the rule is there; the YAML conversion
here is exactly the one YAML install, package install and seeding use.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration import (
    WorkspaceMemoryOverCapError,
    build_command_from_definition,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.test_create_workflow_template import (
    InMemoryEventPublisher,
    InMemoryWorkflowRepository,
)
from syn_shared.agents import PhaseModelDefaults

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_YAML = """id: big-build
name: Big build
phases:
  - id: build
    name: Build
    order: 1
    prompt_template: build it
{resources}"""


def _yaml(memory_mb: int | None) -> WorkflowDefinition:
    resources = "" if memory_mb is None else f"    resources: {{memory_mb: {memory_mb}}}\n"
    return WorkflowDefinition.from_yaml(_YAML.format(resources=resources))


def _handler(
    repository: InMemoryWorkflowRepository, ceiling: int | None = None
) -> CreateWorkflowTemplateHandler:
    return CreateWorkflowTemplateHandler(
        repository,
        InMemoryEventPublisher(),
        model_defaults=PhaseModelDefaults(),
        memory_ceiling_mb=ceiling,
    )


async def test_yaml_install_refuses_a_request_above_the_deployment_ceiling() -> None:
    """Codex's reproduction: 12288 under the unset ceiling (= the 4096 default)."""
    repository = InMemoryWorkflowRepository()

    with pytest.raises(WorkspaceMemoryOverCapError, match="build"):
        await _handler(repository).handle(build_command_from_definition(_yaml(12288)))

    assert repository.streams == {}


async def test_a_reinstall_that_raises_the_request_above_the_ceiling_keeps_the_stored_one() -> None:
    repository = InMemoryWorkflowRepository()
    await _handler(repository, 8192).handle(build_command_from_definition(_yaml(8192)))
    stored = {stream: list(events) for stream, events in repository.streams.items()}

    with pytest.raises(WorkspaceMemoryOverCapError):
        await _handler(repository, 8192).handle(
            build_command_from_definition(_yaml(12288), version="2", force=True)
        )

    assert repository.streams == stored


async def test_a_request_within_the_ceiling_installs() -> None:
    repository = InMemoryWorkflowRepository()

    await _handler(repository, 16384).handle(build_command_from_definition(_yaml(12288)))

    assert repository.streams
