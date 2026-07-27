"""Tests for the update-workflow-phase slice."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from syn_domain.contexts.orchestration._shared.claude_plugin_ref import ClaudePluginRef
from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.UpdatePhasePromptCommand import (
    UpdatePhasePromptCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowPhaseUpdatedEvent import (
    WorkflowPhaseUpdatedEvent,
)
from syn_domain.contexts.orchestration.slices.update_workflow_phase.UpdateWorkflowPhaseHandler import (
    UpdateWorkflowPhaseHandler,
)
from syn_shared.agents import AgentProvider

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope


# === Test Fixtures ===

_WORKFLOW_ID = "test-workflow-id"


def _create_aggregate_with_phases() -> WorkflowTemplateAggregate:
    """Create a workflow aggregate with two phases for testing updates."""
    aggregate = WorkflowTemplateAggregate()
    create_cmd = CreateWorkflowTemplateCommand(
        aggregate_id=_WORKFLOW_ID,
        name="Test Workflow",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        repository_url="https://github.com/test/repo",
        repository_ref="main",
        phases=[
            PhaseDefinition(
                phase_id="phase-1",
                name="Research Phase",
                order=1,
                description="Initial research",
                prompt_template="Original prompt for phase 1",
                model="sonnet",
                timeout_seconds=300,
                allowed_tools=["Bash", "Read"],
            ),
            PhaseDefinition(
                phase_id="phase-2",
                name="Analysis Phase",
                order=2,
                description="Deep analysis",
                prompt_template="Original prompt for phase 2",
            ),
        ],
    )
    aggregate._handle_command(create_cmd)
    aggregate.mark_events_as_committed()
    return aggregate


# === In-Memory Test Doubles ===


class InMemoryWorkflowRepository:
    """In-memory repository for testing updates."""

    def __init__(self) -> None:
        self.aggregates: dict[str, WorkflowTemplateAggregate] = {}
        self.saved_aggregates: list[WorkflowTemplateAggregate] = []

    def seed(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Pre-load an aggregate for get_by_id."""
        if aggregate.id is not None:
            self.aggregates[aggregate.id] = aggregate

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self.aggregates.get(aggregate_id)

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        self.saved_aggregates.append(aggregate)


class InMemoryEventPublisher:
    """In-memory event publisher for testing."""

    def __init__(self) -> None:
        self.published_events: list[EventEnvelope[Any]] = []

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        self.published_events.extend(events)


# === Aggregate Tests ===


@pytest.mark.unit
class TestUpdatePhasePrompt:
    """Tests for WorkflowTemplateAggregate.update_phase_prompt command handler."""

    def test_update_prompt_emits_event(self) -> None:
        """Updating a phase prompt should emit WorkflowPhaseUpdatedEvent."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt content",
        )

        aggregate._handle_command(command)

        events = aggregate.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.event_type == "WorkflowPhaseUpdated"

    def test_update_prompt_updates_state(self) -> None:
        """Updated prompt should be reflected in aggregate state."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt content",
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.prompt_template == "Updated prompt content"

    def test_update_preserves_other_phases(self) -> None:
        """Updating one phase should not affect other phases."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt content",
        )

        aggregate._handle_command(command)

        phase2 = next(p for p in aggregate.phases if p.phase_id == "phase-2")
        assert phase2.prompt_template == "Original prompt for phase 2"

    def test_reject_nonexistent_phase(self) -> None:
        """Should reject update for a phase_id that doesn't exist."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="nonexistent-phase",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValueError, match="not found in workflow"):
            aggregate._handle_command(command)

    def test_reject_uncreated_aggregate(self) -> None:
        """Should reject update on an aggregate that hasn't been created."""
        aggregate = WorkflowTemplateAggregate()
        command = UpdatePhasePromptCommand(
            aggregate_id="some-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValueError, match="does not exist"):
            aggregate._handle_command(command)

    def test_update_with_model_override(self) -> None:
        """Should update the model field when provided."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            model="opus",
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.model == "opus"

    def test_update_with_timeout_override(self) -> None:
        """Should update timeout_seconds when provided."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            timeout_seconds=600,
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.timeout_seconds == 600

    def test_update_with_allowed_tools_override(self) -> None:
        """Should update allowed_tools when provided."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            allowed_tools=["Bash", "Read", "Write", "Grep"],
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert list(phase.allowed_tools) == ["Bash", "Read", "Write", "Grep"]

    def test_optional_fields_none_preserves_existing(self) -> None:
        """When optional fields are None, existing values should be preserved."""
        aggregate = _create_aggregate_with_phases()
        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
            # model, timeout_seconds, allowed_tools all None
        )

        aggregate._handle_command(command)

        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.model == "sonnet"  # preserved from creation
        assert phase.timeout_seconds == 300  # preserved from creation
        assert list(phase.allowed_tools) == ["Bash", "Read"]  # preserved


# === Handler Tests ===


class TestUpdateWorkflowPhaseHandler:
    """Tests for UpdateWorkflowPhaseHandler application service."""

    @pytest.mark.asyncio
    async def test_handler_loads_and_saves(self) -> None:
        """Handler should load the aggregate, dispatch, and save."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        aggregate = _create_aggregate_with_phases()
        repository.seed(aggregate)
        handler = UpdateWorkflowPhaseHandler(repository, publisher)

        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
        )

        result = await handler.handle(command)

        assert result == _WORKFLOW_ID
        assert len(repository.saved_aggregates) == 1

    @pytest.mark.asyncio
    async def test_handler_publishes_events(self) -> None:
        """Handler should publish the WorkflowPhaseUpdatedEvent."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        aggregate = _create_aggregate_with_phases()
        repository.seed(aggregate)
        handler = UpdateWorkflowPhaseHandler(repository, publisher)

        command = UpdatePhasePromptCommand(
            aggregate_id=_WORKFLOW_ID,
            phase_id="phase-1",
            prompt_template="Updated prompt",
        )

        await handler.handle(command)

        assert len(publisher.published_events) == 1
        assert publisher.published_events[0].event.event_type == "WorkflowPhaseUpdated"

    @pytest.mark.asyncio
    async def test_handler_raises_on_missing_workflow(self) -> None:
        """Handler should raise ValueError when workflow not found."""
        repository = InMemoryWorkflowRepository()
        publisher = InMemoryEventPublisher()
        handler = UpdateWorkflowPhaseHandler(repository, publisher)

        command = UpdatePhasePromptCommand(
            aggregate_id="nonexistent-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValueError, match="not found"):
            await handler.handle(command)


# === Event Tests ===


class TestWorkflowPhaseUpdatedEvent:
    """Tests for WorkflowPhaseUpdatedEvent domain event."""

    def test_event_has_correct_type(self) -> None:
        """Event should have correct event_type from @event decorator."""
        event = WorkflowPhaseUpdatedEvent(
            workflow_id="test-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )
        assert event.event_type == "WorkflowPhaseUpdated"

    def test_event_is_immutable(self) -> None:
        """Event should be immutable (frozen Pydantic model)."""
        from pydantic import ValidationError

        event = WorkflowPhaseUpdatedEvent(
            workflow_id="test-id",
            phase_id="phase-1",
            prompt_template="Some prompt",
        )

        with pytest.raises(ValidationError):
            event.prompt_template = "Changed"  # type: ignore[misc]



class TestPhaseUpdatePreservesDelegationFields:
    """Regression: prompt/model edits must not wipe provider/allow_delegation/skills."""

    def test_prompt_update_preserves_provider_and_delegation(self) -> None:
        # A codex phase is headless, so it carries no agent_id; the fields that
        # must survive a prompt-only edit are provider, allow_delegation, and the
        # #772 skills / #726 claude_plugins.
        agg = WorkflowTemplateAggregate()
        agg._handle_command(
            CreateWorkflowTemplateCommand(
                aggregate_id=_WORKFLOW_ID,
                name="W",
                workflow_type=WorkflowType.RESEARCH,
                classification=WorkflowClassification.SIMPLE,
                repository_url="",
                repository_ref="main",
                phases=[
                    PhaseDefinition(
                        phase_id="phase-1",
                        name="p",
                        order=1,
                        prompt_template="orig",
                        provider=AgentProvider.CODEX,
                        allow_delegation=True,
                        skills=(
                            SkillRef(
                                skill_name="review", source_url="acme/skills", version="v1.0.0"
                            ),
                        ),
                        claude_plugins=(
                            ClaudePluginRef(
                                name="sdlc", source_url="acme/plugins", version="v1.0.0"
                            ),
                        ),
                    )
                ],
            )
        )
        agg.mark_events_as_committed()
        agg._handle_command(
            UpdatePhasePromptCommand(
                aggregate_id=_WORKFLOW_ID,
                phase_id="phase-1",
                prompt_template="new",
            )
        )
        p = next(x for x in agg.phases if x.phase_id == "phase-1")
        assert p.provider == AgentProvider.CODEX
        assert p.allow_delegation is True
        assert p.prompt_template == "new"
        # #772 skills + #726 claude_plugins must survive a prompt edit too.
        assert len(p.skills) == 1 and p.skills[0].skill_name == "review"
        assert len(p.claude_plugins) == 1 and p.claude_plugins[0].name == "sdlc"


class TestPhaseProviderUpdate:
    """Provider is settable via update and preserved on prompt-only edits."""

    def _codex_aggregate(self) -> WorkflowTemplateAggregate:
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(
            CreateWorkflowTemplateCommand(
                aggregate_id=_WORKFLOW_ID,
                name="Codex Workflow",
                workflow_type=WorkflowType.RESEARCH,
                classification=WorkflowClassification.SIMPLE,
                repository_url="",
                repository_ref="main",
                phases=[
                    PhaseDefinition(
                        phase_id="phase-1",
                        name="Codex Phase",
                        order=1,
                        prompt_template="original",
                        provider=AgentProvider.CODEX,
                    ),
                ],
            )
        )
        aggregate.mark_events_as_committed()
        return aggregate

    def test_update_can_set_provider(self) -> None:
        aggregate = _create_aggregate_with_phases()
        aggregate._handle_command(
            UpdatePhasePromptCommand(
                aggregate_id=_WORKFLOW_ID,
                phase_id="phase-1",
                prompt_template="kept",
                provider=AgentProvider.CODEX,
            )
        )
        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.provider == AgentProvider.CODEX

    def test_prompt_only_update_preserves_provider(self) -> None:
        # Regression: _apply_phase_update used to drop provider on any edit,
        # silently reverting a codex phase to the claude default.
        aggregate = self._codex_aggregate()
        aggregate._handle_command(
            UpdatePhasePromptCommand(
                aggregate_id=_WORKFLOW_ID,
                phase_id="phase-1",
                prompt_template="new prompt",
            )
        )
        phase = next(p for p in aggregate.phases if p.phase_id == "phase-1")
        assert phase.provider == AgentProvider.CODEX
        assert phase.prompt_template == "new prompt"

    def test_provider_switch_to_headless_clears_stale_agent_id(self) -> None:
        # Regression: switching an interactive phase (agent_id set) to a headless
        # provider must drop agent_id, else AgentConfiguration.__post_init__ rejects
        # the codex + non-codex-agent_id combo at execution.
        agg = WorkflowTemplateAggregate()
        agg._handle_command(
            CreateWorkflowTemplateCommand(
                aggregate_id=_WORKFLOW_ID,
                name="W",
                workflow_type=WorkflowType.RESEARCH,
                classification=WorkflowClassification.SIMPLE,
                repository_url="",
                repository_ref="main",
                phases=[
                    PhaseDefinition(
                        phase_id="phase-1",
                        name="p",
                        order=1,
                        prompt_template="orig",
                        provider="claude-interactive",
                        agent_id="gemini",
                    )
                ],
            )
        )
        agg.mark_events_as_committed()
        agg._handle_command(
            UpdatePhasePromptCommand(
                aggregate_id=_WORKFLOW_ID,
                phase_id="phase-1",
                prompt_template="new",
                provider="codex",
            )
        )
        phase = next(p for p in agg.phases if p.phase_id == "phase-1")
        assert phase.provider == AgentProvider.CODEX
        assert phase.agent_id is None

    def test_prompt_update_preserves_skills_and_plugins(self) -> None:
        agg = WorkflowTemplateAggregate()
        agg._handle_command(
            CreateWorkflowTemplateCommand(
                aggregate_id=_WORKFLOW_ID,
                name="W",
                workflow_type=WorkflowType.RESEARCH,
                classification=WorkflowClassification.SIMPLE,
                repository_url="",
                repository_ref="main",
                phases=[
                    PhaseDefinition(
                        phase_id="phase-1",
                        name="p",
                        order=1,
                        prompt_template="orig",
                        skills=(
                            SkillRef(
                                skill_name="review", source_url="acme/skills", version="v1.0.0"
                            ),
                        ),
                        claude_plugins=(
                            ClaudePluginRef(
                                name="sdlc", source_url="acme/plugins", version="v1.0.0"
                            ),
                        ),
                    )
                ],
            )
        )
        agg.mark_events_as_committed()
        agg._handle_command(
            UpdatePhasePromptCommand(
                aggregate_id=_WORKFLOW_ID, phase_id="phase-1", prompt_template="new"
            )
        )
        phase = next(p for p in agg.phases if p.phase_id == "phase-1")
        assert len(phase.skills) == 1 and phase.skills[0].skill_name == "review"
        assert len(phase.claude_plugins) == 1 and phase.claude_plugins[0].name == "sdlc"
