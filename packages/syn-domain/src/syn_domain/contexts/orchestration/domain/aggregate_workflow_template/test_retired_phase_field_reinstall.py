"""A template stored with `can_open_pr` reinstalls as unchanged.

Every template installed before the retirement has `can_open_pr` in the phases
of its `WorkflowTemplateCreated` event. The reinstall fingerprint compares the
stored phases with the incoming ones, so if the stored key survived replay as
a field, the same package at the same version and digest would look like new
content and be refused as already installed (#822). The author deletes the
line, as the notice tells them to, and that must be a no-op too.
"""

from __future__ import annotations

import asyncio

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.test_create_workflow_template import (
    InMemoryEventPublisher,
    InMemoryWorkflowRepository,
)
from syn_shared.agents import PhaseModelDefaults

pytestmark = pytest.mark.unit

WORKFLOW_ID = "retired-reinstall"
VERSION = "1.0.0"
DIGEST = "abc"


def _yaml(phase_extra: str) -> str:
    return f"""
id: {WORKFLOW_ID}
name: Retired reinstall
type: custom
classification: simple
phases:
  - id: open_pr
    name: Open PR
    order: 1
    prompt_template: "Open the PR."
{phase_extra}"""


def _install(handler: CreateWorkflowTemplateHandler, content: str) -> bool:
    command = build_command_from_definition(
        WorkflowDefinition.from_yaml(content), version=VERSION, source_digest=DIGEST
    )
    return asyncio.run(handler.handle(command)).changed


def _stored_before_retirement() -> tuple[CreateWorkflowTemplateHandler, InMemoryWorkflowRepository]:
    """A repository whose stream holds the created event as written pre-retirement."""
    repo = InMemoryWorkflowRepository()
    handler = CreateWorkflowTemplateHandler(
        repo, InMemoryEventPublisher(), model_defaults=PhaseModelDefaults()
    )
    assert _install(handler, _yaml("")) is True

    [envelope] = repo.streams[WORKFLOW_ID]
    payload = envelope.event.model_dump(mode="json")
    payload["phases"] = [{**p, "can_open_pr": True} for p in payload["phases"]]
    repo.streams[WORKFLOW_ID] = [
        EventEnvelope[DomainEvent](
            event=WorkflowTemplateCreatedEvent.model_validate(payload),
            metadata=envelope.metadata,
        )
    ]
    return handler, repo


class TestReinstallOverAStoredRetiredKey:
    def test_the_same_package_with_the_line_deleted_is_unchanged(self) -> None:
        """What the notice asks the author to do must not be a new version."""
        handler, repo = _stored_before_retirement()

        assert _install(handler, _yaml("")) is False
        assert len(repo.streams[WORKFLOW_ID]) == 1

    def test_the_same_package_still_carrying_the_line_is_unchanged(self) -> None:
        """Only fails on a partial landing: the key dropped on one side only."""
        handler, repo = _stored_before_retirement()

        assert _install(handler, _yaml("    can_open_pr: true\n")) is False
        assert len(repo.streams[WORKFLOW_ID]) == 1
