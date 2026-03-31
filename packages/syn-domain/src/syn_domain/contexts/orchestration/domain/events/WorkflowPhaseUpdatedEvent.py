"""WorkflowPhaseUpdated event - represents the fact that a workflow phase was updated."""

from __future__ import annotations

from event_sourcing import DomainEvent, event


@event("WorkflowPhaseUpdated", "v1")
class WorkflowPhaseUpdatedEvent(DomainEvent):
    """Event emitted when a workflow phase's prompt or config is updated.

    Extends DomainEvent from event_sourcing SDK.
    Events represent facts - what happened.
    """

    # Workflow identity
    workflow_id: str

    # Target phase
    phase_id: str

    # Updated prompt content
    prompt_template: str

    # Optional config overrides (None = unchanged from previous state)
    model: str | None = None
    timeout_seconds: int | None = None
    allowed_tools: list[str] | None = None
