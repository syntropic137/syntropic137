"""Trigger rule read model.

Represents the current state of a trigger rule, projected from events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)


@dataclass
class TriggerRule:
    """Read model for a trigger rule.

    Attributes:
        trigger_id: Unique identifier for the trigger rule.
        name: Human-readable name.
        event: GitHub event type (e.g. "check_run.completed").
        conditions: List of condition dicts.
        repository: Target repository (owner/repo).
        installation_id: GitHub App installation ID.
        workflow_id: Workflow to dispatch.
        input_mapping: Map of workflow input names to payload paths.
        config: Safety configuration dict.
        status: Current trigger status.
        fire_count: Total number of times this trigger has fired.
        last_fired_at: When the trigger last fired.
        created_by: User or agent that registered the trigger.
        created_at: When the trigger was registered.
    """

    trigger_id: str
    name: str
    event: str = ""
    conditions: list[dict] = field(default_factory=list)
    repository: str = ""
    installation_id: str = ""
    workflow_id: str = ""
    input_mapping: dict[str, str] = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    status: TriggerStatus = TriggerStatus.ACTIVE
    fire_count: int = 0
    last_fired_at: datetime | None = None
    created_by: str = ""
    created_at: datetime | None = None
