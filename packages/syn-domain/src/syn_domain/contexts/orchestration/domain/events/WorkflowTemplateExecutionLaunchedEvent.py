"""WorkflowTemplateExecutionLaunched event - an execution of this template was launched."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves the annotation at runtime

from event_sourcing import DomainEvent, event


@event("WorkflowTemplateExecutionLaunched", "v1")
class WorkflowTemplateExecutionLaunchedEvent(DomainEvent):
    """Recorded on the template's stream before the execution's own stream exists.

    It puts every launch and every archive of a template on one stream, so the
    two cannot both succeed against the same version (#1588): whichever saves
    second conflicts and re-decides.
    """

    workflow_id: str
    execution_id: str
    launched_at: datetime
