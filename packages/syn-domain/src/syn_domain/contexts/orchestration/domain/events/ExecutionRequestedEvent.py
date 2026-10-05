"""ExecutionRequested event (#1557)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves it at runtime

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    EvalBaselinePin,  # noqa: TC001 - Pydantic resolves it at runtime
)


@event("ExecutionRequested", "v1")
class ExecutionRequestedEvent(DomainEvent):
    """A direct start was admitted, durably, before the caller was told so.

    Carries everything the start needs, as primitives, so a restart can start
    it from this event alone. The execution it names does not exist yet: its
    own stream opens when the start gets an execution-budget slot.
    """

    execution_id: str
    workflow_id: str
    inputs: dict[str, str] = Field(default_factory=dict)
    task: str | None = None
    repos: list[str] = Field(default_factory=list)
    """Repository slugs (`owner/name`), as `RepositoryRef.slug` writes them."""
    tags: list[str] = Field(default_factory=list)
    eval_id: str | None = None
    """The eval the start joins (#967), resolved and admitted when it was accepted.

    On an event without ``eval_selection`` it is only the eval the launch
    named explicitly, if any: see ``eval_selection``."""
    eval_ordinary: bool = False
    """The launch asked for an ordinary run, suppressing the workflow's default eval."""
    eval_selection: str | None = None
    """How the eval was chosen (an ``EvalSelection`` value), resolved ONCE, at acceptance.

    None only on an event written before requests carried their resolved eval:
    that request still holds just the launch's choice, and re-resolves it
    against the workflow's default when it starts. Every event written since
    carries the answer, so a start recovered after a restart joins the eval it
    was accepted into, at the SHAs frozen then, whatever the default is now."""
    eval_baseline: list[EvalBaselinePin] | None = None
    """The admitted eval's frozen baseline, or None for a start in no eval."""
    requested_at: datetime
