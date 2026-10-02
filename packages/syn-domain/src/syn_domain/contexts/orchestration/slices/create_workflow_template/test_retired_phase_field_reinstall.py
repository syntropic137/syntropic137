"""Reinstalling an unchanged package over a pre-retirement template is a no-op.

Templates installed before `can_open_pr` was retired carry it in every stored
phase. Reinstall identity compares the stored definition with the incoming
one field by field (#822), so if either side still declared the field the
two would differ: a same-version reinstall would be refused as
already-installed, and every package that set the key would need `--force` to
reinstall exactly what it already has. That is why the YAML field, the domain
field and the event tolerance retire in ONE change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_shared.agents import PhaseModelDefaults

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )

pytestmark = pytest.mark.unit

WORKFLOW_ID = "retired-reinstall"
VERSION = "1.0.0"
DIGEST = "abc"


def _yaml(phase_line: str = "") -> str:
    extra = f"    {phase_line}\n" if phase_line else ""
    return (
        f"id: {WORKFLOW_ID}\n"
        "name: Retired reinstall\n"
        "type: custom\n"
        "phases:\n"
        "  - id: open_pr\n"
        "    name: Open PR\n"
        "    order: 1\n"
        "    prompt_template: open it\n" + extra
    )


def _command(phase_line: str = "") -> CreateWorkflowTemplateCommand:
    """The command the install endpoint builds from this YAML."""
    return build_command_from_definition(
        WorkflowDefinition.from_yaml(_yaml(phase_line)),
        version=VERSION,
        source_digest=DIGEST,
    )


class _StoredEvent:
    """A stored event as the gRPC store replays it: generic and dict-backed."""

    def __init__(self, data: object) -> None:
        self._data = data

    def model_dump(self) -> object:
        return self._data


class _Repository:
    """Hands back the template rehydrated from the stored payload."""

    def __init__(self, aggregate: WorkflowTemplateAggregate) -> None:
        self._aggregate = aggregate
        self.saved = 0

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self._aggregate if aggregate_id == WORKFLOW_ID else None

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        self.saved += 1


class _Publisher:
    def __init__(self) -> None:
        self.events: list[EventEnvelope[DomainEvent]] = []

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        self.events.extend(events)


def _stored_before_retirement() -> WorkflowTemplateAggregate:
    """Install the package, then replay its Created event with the key put back.

    Installing through the real handler gives the payload exactly as it is
    stored today (model provenance included); the key is then written where
    it sat in every phase before retirement.
    """
    created = WorkflowTemplateAggregate()
    created.create_workflow(_command())
    payload = created.get_uncommitted_events()[0].event.model_dump(mode="json")
    payload["phases"] = [{**phase, "can_open_pr": True} for phase in payload["phases"]]

    stored = WorkflowTemplateAggregate()
    stored._initialize(WORKFLOW_ID)
    stored.on_workflow_created(_StoredEvent(payload))  # type: ignore[arg-type]
    return stored


async def _reinstall(phase_line: str) -> tuple[bool, _Repository, _Publisher]:
    repository = _Repository(_stored_before_retirement())
    publisher = _Publisher()
    handler = CreateWorkflowTemplateHandler(
        repository,  # type: ignore[arg-type]
        publisher,  # type: ignore[arg-type]
        model_defaults=PhaseModelDefaults(),
    )
    outcome = await handler.handle(_command(phase_line))
    return outcome.changed, repository, publisher


class TestReinstallOverAPreRetirementTemplate:
    @pytest.mark.asyncio
    async def test_package_without_the_key_is_identical(self) -> None:
        """The author deleted the line: same version, same digest, no change.

        Were the two definitions to differ, the same version would be refused
        with WorkflowTemplateVersionAlreadyInstalledError and this would raise.
        """
        changed, repository, publisher = await _reinstall("")

        assert changed is False
        assert repository.saved == 0
        assert publisher.events == []

    @pytest.mark.asyncio
    async def test_package_still_carrying_the_key_is_identical(self) -> None:
        """The author has not touched it yet: still the same install."""
        changed, repository, publisher = await _reinstall("can_open_pr: true")

        assert changed is False
        assert repository.saved == 0
        assert publisher.events == []
