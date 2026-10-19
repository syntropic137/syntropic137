"""A phase's fallback_agent cannot be installed onto a retired Claude model.

Provisioning builds the fallback's command eagerly, so a retired fallback that
got past install would fail every run of the phase before its allowed primary
started. The input here is the author's YAML, converted the way the install
path converts it, and the repository double replays what it stores.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.test_create_workflow_template import (
    InMemoryEventPublisher,
    InMemoryWorkflowRepository,
)
from syn_shared.agents import PhaseModelDefaults, RetiredModelError

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_YAML = """id: fallback-model
name: Fallback model
type: research
classification: standard
phases:
  - id: p
    name: P
    order: 1
    prompt_template: Probe
    model: opus
    fallback_agent: {fallback}
"""


def _command(fallback: str) -> CreateWorkflowTemplateCommand:
    definition = WorkflowDefinition.from_yaml(_YAML.format(fallback=fallback))
    return CreateWorkflowTemplateCommand(
        aggregate_id="wf",
        name=definition.name,
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.STANDARD,
        phases=[phase.to_domain() for phase in definition.phases],
    )


def _handler(repository: InMemoryWorkflowRepository) -> CreateWorkflowTemplateHandler:
    return CreateWorkflowTemplateHandler(
        repository, InMemoryEventPublisher(), model_defaults=PhaseModelDefaults()
    )


@pytest.mark.parametrize(
    "fallback",
    [
        "{provider: claude, model: claude-sonnet-4-5}",
        "{provider: claude, model: Claude-Sonnet-4-5-20250929}",
        "{provider: claude, model: claude-haiku-4-5}",
    ],
)
async def test_install_refuses_a_retired_fallback_before_saving(fallback: str) -> None:
    repository = InMemoryWorkflowRepository()
    with pytest.raises(RetiredModelError):
        await _handler(repository).handle(_command(fallback))
    assert repository.streams == {}


async def test_reinstall_refuses_a_retired_fallback_and_keeps_the_stored_one() -> None:
    repository = InMemoryWorkflowRepository()
    await _handler(repository).handle(_command("{provider: claude, model: sonnet}"))
    before = list(repository.streams["wf"])

    with pytest.raises(RetiredModelError):
        await _handler(repository).handle(_command("{provider: claude, model: claude-sonnet-4-5}"))

    assert repository.streams["wf"] == before


async def test_an_allowed_fallback_installs_as_declared() -> None:
    repository = InMemoryWorkflowRepository()
    await _handler(repository).handle(_command("{provider: claude, model: sonnet}"))
    aggregate = await repository.get_by_id("wf")
    assert aggregate is not None
    [phase] = aggregate.phases
    assert phase.fallback_agent is not None
    assert phase.fallback_agent.model == "sonnet"
