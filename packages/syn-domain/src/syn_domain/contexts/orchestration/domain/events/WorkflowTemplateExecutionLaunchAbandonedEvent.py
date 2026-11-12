"""WorkflowTemplateExecutionLaunchAbandoned event - a launch's start gave up (#1635)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves the annotation at runtime

from event_sourcing import DomainEvent, event


@event("WorkflowTemplateExecutionLaunchAbandoned", "v1")
class WorkflowTemplateExecutionLaunchAbandonedEvent(DomainEvent):
    """The start of a recorded launch failed, so it is no longer in flight.

    Recorded on the template's stream beside the launch it ends. It ends only
    the wait for the execution's stream: an execution whose stream does exist
    is judged by its own status, whatever this says. A later launch of the
    same execution id renews the launch and supersedes this. ``launched_at``
    names the launch it ends, so one start of an id giving up never releases
    another start of the same id that renewed the launch meanwhile.
    """

    workflow_id: str
    execution_id: str
    launched_at: datetime
    abandoned_at: datetime
