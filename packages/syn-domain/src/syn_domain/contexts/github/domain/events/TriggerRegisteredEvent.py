"""Trigger Registered domain event.

Emitted when a new trigger rule is registered.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field, field_validator


@event("github.TriggerRegistered", "v1")
class TriggerRegisteredEvent(DomainEvent):
    """Event emitted when a trigger rule is registered.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        name: Human-readable name for the trigger.
        event: GitHub event type (e.g. "check_run.completed").
        conditions: List of condition dicts to evaluate.
        repository: Target repository (owner/repo).
        installation_id: GitHub App installation ID.
        workflow_id: Workflow to dispatch when trigger fires.
        input_mapping: Map of workflow input names to payload paths.
        config: Safety configuration dict.
        created_by: User or agent that registered the trigger.
    """

    trigger_id: str
    name: str
    event: str
    conditions: tuple[dict, ...] = ()
    repository: str = ""
    installation_id: str = ""
    workflow_id: str = ""
    input_mapping: dict[str, str] = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    created_by: str = ""

    @field_validator("trigger_id")
    @classmethod
    def validate_trigger_id(cls, v: str) -> str:
        """Ensure trigger_id is provided."""
        if not v:
            raise ValueError("trigger_id is required")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is provided."""
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, v: str) -> str:
        """Ensure repository is provided."""
        if not v:
            raise ValueError("repository is required")
        return v
