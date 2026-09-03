"""Publish a review workflow's verdict to the pull request it judged (#1097).

A review that completes and writes an artifact nobody fetches is
indistinguishable from a review that never ran, while costing the same. This
ProcessManager closes that gap: when a ``review``-type workflow execution that
named a pull request completes, its final deliverable is posted as a comment on
that pull request.

PROJECTION SIDE (``handle_event``): accumulates the to-do record -- which pull
  request, which artifact, is it finished -- purely from the event stream.
  Runs during replay and live. No external calls.

PROCESSOR SIDE (``process_pending``): posts. Live only, and idempotent against
  GitHub itself: a verdict whose marker is already on the pull request is never
  posted twice, however often the projection is rebuilt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import (
    DomainEvent,
    EventEnvelope,
    ProcessManager,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from syn_domain.contexts.github._shared.projection_names import (
    REVIEW_VERDICTS,
    REVIEW_WORKFLOWS,
)
from syn_domain.contexts.github.slices.publish_review_verdict.review_target import (
    review_target_from_inputs,
)
from syn_domain.contexts.github.slices.publish_review_verdict.verdict_comment import (
    VerdictMarker,
    find_markers,
    render_verdict_comment,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from event_sourcing import ProjectionStore
    from event_sourcing.core.checkpoint import DispatchContext

    from syn_domain.contexts.github.slices.publish_review_verdict.pull_request_conversation import (
        PullRequestConversation,
    )

logger = logging.getLogger(__name__)

#: Orchestration and artifact events are unnamespaced; only github's own
#: events carry the ``github.`` prefix.
_SUBSCRIBED_EVENTS = {
    "WorkflowTemplateCreated",
    "WorkflowTemplateUpdated",
    "WorkflowExecutionStarted",
    "ArtifactCreated",
    "WorkflowCompleted",
}

_REVIEW = "review"

RUNNING = "running"
READY = "ready"
POSTED = "posted"
SKIPPED = "skipped"


def _as_text(value: object) -> str:
    """Read a stored or serialized value as a string; absent becomes empty."""
    return "" if value is None else str(value)


def _as_number(value: object) -> int:
    """Read a stored value as an int; anything unreadable becomes 0."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


class _EventFields:
    """Read-only view over one event's serialized fields.

    This publisher reacts to events owned by three other bounded contexts.
    Importing their classes would couple a github projection to orchestration's
    and artifacts' aggregates, so it reads the serialized form instead -- but
    it reads it here, once, rather than at every use site.
    """

    __slots__ = ("_data",)

    def __init__(self, event: DomainEvent) -> None:
        self._data: Mapping[str, object] = event.model_dump()

    def text(self, *names: str) -> str:
        """The first of ``names`` that carries a value, as a string."""
        for name in names:
            value = _as_text(self._data.get(name))
            if value:
                return value
        return ""

    def flag(self, name: str) -> bool:
        return bool(self._data.get(name))

    def mapping(self, name: str) -> Mapping[str, object]:
        value = self._data.get(name)
        return value if isinstance(value, dict) else {}


@dataclass(slots=True)
class _VerdictTodo:
    """One review execution's progress towards a published verdict."""

    execution_id: str
    repository: str
    pr_number: int
    status: str
    verdict: str = ""
    artifact_id: str = ""

    def to_record(self) -> dict[str, str | int]:
        return {
            "execution_id": self.execution_id,
            "repository": self.repository,
            "pr_number": self.pr_number,
            "status": self.status,
            "verdict": self.verdict,
            "artifact_id": self.artifact_id,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> _VerdictTodo:
        return cls(
            execution_id=_as_text(record.get("execution_id")),
            repository=_as_text(record.get("repository")),
            pr_number=_as_number(record.get("pr_number")),
            status=_as_text(record.get("status")) or RUNNING,
            verdict=_as_text(record.get("verdict")),
            artifact_id=_as_text(record.get("artifact_id")),
        )


class ReviewVerdictPublisher(ProcessManager):
    """Posts each completed review execution's verdict to its pull request."""

    PROJECTION_NAME = REVIEW_VERDICTS
    VERSION = 1

    def __init__(
        self,
        store: ProjectionStore,
        conversation: PullRequestConversation | None = None,
    ) -> None:
        """Args:
        store: Projection store holding the to-do list.
        conversation: Port onto the pull request's comments. None disables
            publishing (the GitHub App is not configured), leaving the to-do
            records to be posted once it is.
        """
        self._store = store
        self._conversation = conversation

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return _SUBSCRIBED_EVENTS

    async def clear_all_data(self) -> None:
        await self._store.delete_all(self.PROJECTION_NAME)
        await self._store.delete_all(REVIEW_WORKFLOWS)

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """One verdict per execution."""
        return str(todo_item.get("execution_id", ""))

    # ------------------------------------------------------------------
    # Projection side
    # ------------------------------------------------------------------

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        """Accumulate the to-do record. Pure: no posting happens here."""
        event_type = envelope.metadata.event_type or ""
        fields = _EventFields(envelope.event)

        try:
            if event_type in ("WorkflowTemplateCreated", "WorkflowTemplateUpdated"):
                await self._note_workflow_type(fields)
            elif event_type == "WorkflowExecutionStarted":
                await self._begin(fields)
            elif event_type == "ArtifactCreated":
                await self._note_deliverable(fields)
            elif event_type == "WorkflowCompleted":
                await self._mark_ready(fields)

            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=envelope.metadata.global_nonce or 0,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS
        except Exception:
            logger.exception("Error in review verdict publisher", extra={"event": event_type})
            return ProjectionResult.FAILURE

    async def _note_workflow_type(self, fields: _EventFields) -> None:
        """Remember whether a workflow produces reviews."""
        workflow_id = fields.text("aggregate_id", "workflow_id")
        if not workflow_id:
            return
        await self._store.save(
            REVIEW_WORKFLOWS,
            workflow_id,
            {
                "workflow_id": workflow_id,
                "is_review": fields.text("workflow_type") == _REVIEW,
            },
        )

    async def _begin(self, fields: _EventFields) -> None:
        """Start tracking a review execution that named a pull request."""
        execution_id = fields.text("execution_id")
        if not execution_id or not await self._is_review_workflow(fields.text("workflow_id")):
            return

        target = review_target_from_inputs(fields.mapping("inputs"))
        if target is None:
            logger.info(
                "Review execution %s names no pull request; its verdict will not be published",
                execution_id,
            )
            return

        await self._save(
            _VerdictTodo(
                execution_id=execution_id,
                repository=target.repository,
                pr_number=target.pr_number,
                status=RUNNING,
            )
        )

    async def _note_deliverable(self, fields: _EventFields) -> None:
        """Keep the latest phase's primary deliverable -- the last one is the verdict."""
        if not fields.flag("is_primary_deliverable"):
            return
        todo = await self._load(fields.text("execution_id"))
        if todo is None:
            return
        todo.verdict = fields.text("content")
        todo.artifact_id = fields.text("artifact_id")
        await self._save(todo)

    async def _mark_ready(self, fields: _EventFields) -> None:
        """The execution finished: its verdict is now complete and postable."""
        todo = await self._load(fields.text("execution_id"))
        if todo is None or todo.status != RUNNING:
            return
        todo.status = READY
        await self._save(todo)

    async def _is_review_workflow(self, workflow_id: str) -> bool:
        record = await self._store.get(REVIEW_WORKFLOWS, workflow_id)
        return bool(record and record.get("is_review"))

    async def _load(self, execution_id: str) -> _VerdictTodo | None:
        if not execution_id:
            return None
        record = await self._store.get(self.PROJECTION_NAME, execution_id)
        return _VerdictTodo.from_record(record) if record else None

    async def _save(self, todo: _VerdictTodo) -> None:
        await self._store.save(self.PROJECTION_NAME, todo.execution_id, todo.to_record())

    # ------------------------------------------------------------------
    # Processor side
    # ------------------------------------------------------------------

    async def process_pending(self) -> int:
        """Post every ready verdict. Live only, idempotent, returns how many posted."""
        if self._conversation is None:
            return 0

        posted = 0
        for record in await self._store.query(self.PROJECTION_NAME, filters={"status": READY}):
            todo = _VerdictTodo.from_record(record)
            try:
                if await self._publish(todo):
                    posted += 1
            except Exception:
                logger.exception(
                    "Could not publish verdict for %s to %s#%s -- will retry",
                    todo.execution_id,
                    todo.repository,
                    todo.pr_number,
                )
        return posted

    async def _publish(self, todo: _VerdictTodo) -> bool:
        """Post one verdict. Returns True when a comment was created."""
        assert self._conversation is not None

        if not todo.verdict:
            logger.warning(
                "Review execution %s completed with no deliverable to publish",
                todo.execution_id,
            )
            todo.status = SKIPPED
            await self._save(todo)
            return False

        markers = find_markers(
            await self._conversation.comment_bodies(todo.repository, todo.pr_number)
        )
        if any(m.execution_id == todo.execution_id for m in markers):
            logger.info("Verdict for %s is already on the pull request", todo.execution_id)
            todo.status = POSTED
            await self._save(todo)
            return False

        head = await self._conversation.head_sha(todo.repository, todo.pr_number)
        body = render_verdict_comment(
            marker=VerdictMarker(execution_id=todo.execution_id, head_sha=head),
            verdict=todo.verdict,
            supersedes=markers[-1] if markers else None,
            artifact_id=todo.artifact_id,
        )
        await self._conversation.post_comment(todo.repository, todo.pr_number, body)

        todo.status = POSTED
        await self._save(todo)
        logger.info(
            "Published verdict for %s on %s#%s",
            todo.execution_id,
            todo.repository,
            todo.pr_number,
        )
        return True
