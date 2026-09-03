"""A review verdict must reach the pull request it judged (#1097).

These tests drive the whole hop the way production does -- real domain events
through ``handle_event``, then ``process_pending`` -- and assert on what the
pull request ends up holding, not on the publisher's internal records. The
comment body is the deliverable; a to-do row that says ``posted`` while GitHub
holds nothing is exactly the failure #1097 was opened about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import (
    DomainEvent,
    EventEnvelope,
    EventMetadata,
    MemoryCheckpointStore,
)

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.artifacts._shared.value_objects import ArtifactType, ContentType
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import (
    ArtifactCreatedEvent,
)
from syn_domain.contexts.github.slices.publish_review_verdict.projection import (
    ReviewVerdictPublisher,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = "syntropic137/syntropic137"
PR = 1042
WORKFLOW_ID = "wf-sdlc-pr-review-v1"
EXECUTION_ID = "exec-32ea5ed0"
HEAD_SHA = "9d5908a6c1f4e77b0a2d3915ee4c8b6721fd0e3a"

#: The report phase's deliverable. Nothing but publishing puts this on the pull
#: request, so finding it in a comment body means the hop ran end to end.
VERDICT = "**Verdict.** The claim does not hold: `pr_number` is never persisted."


@dataclass
class FakeConversation:
    """A pull request's comment thread, as the publisher is allowed to see it."""

    head: str = HEAD_SHA
    comments: list[str] = field(default_factory=list)
    asked: list[tuple[str, int]] = field(default_factory=list)

    async def head_sha(self, repository: str, pr_number: int) -> str:
        self.asked.append((repository, pr_number))
        return self.head

    async def comment_bodies(self, repository: str, pr_number: int) -> list[str]:
        return list(self.comments)

    async def post_comment(self, repository: str, pr_number: int, body: str) -> None:
        assert repository == REPO, f"posted to the wrong repository: {repository}"
        assert pr_number == PR, f"posted to the wrong pull request: {pr_number}"
        self.comments.append(body)


def _envelope(event: DomainEvent, nonce: int) -> EventEnvelope[DomainEvent]:
    """Wrap an event as the coordinator would deliver it."""
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            stream_name=f"stream-{nonce}",
            aggregate_id=f"agg-{nonce}",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            global_nonce=nonce,
            event_type=type(event).event_type,
        ),
    )


def _template(workflow_type: WorkflowType = WorkflowType.REVIEW) -> WorkflowTemplateCreatedEvent:
    return WorkflowTemplateCreatedEvent(
        workflow_id=WORKFLOW_ID,
        name="SDLC: Verify a PR's central claim (v1)",
        workflow_type=workflow_type,
        classification=WorkflowClassification.STANDARD,
        repository_url=f"https://github.com/{REPO}",
        repository_ref="main",
        phases=[],
    )


def _started(
    inputs: Mapping[str, object], execution_id: str = EXECUTION_ID
) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        workflow_name="SDLC: Verify a PR's central claim (v1)",
        started_at=datetime.now(UTC),
        total_phases=3,
        inputs=inputs,
    )


def _artifact(
    phase_id: str,
    content: str,
    artifact_id: str,
    execution_id: str = EXECUTION_ID,
) -> ArtifactCreatedEvent:
    return ArtifactCreatedEvent(
        artifact_id=artifact_id,
        workflow_id=WORKFLOW_ID,
        phase_id=phase_id,
        execution_id=execution_id,
        artifact_type=ArtifactType.MARKDOWN,
        content_type=ContentType.TEXT_MARKDOWN,
        content=content,
        content_hash=f"sha256:{artifact_id}",
        size_bytes=len(content),
    )


def _completed(execution_id: str = EXECUTION_ID) -> WorkflowCompletedEvent:
    return WorkflowCompletedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        completed_at=datetime.now(UTC),
        total_phases=3,
        completed_phases=3,
        total_input_tokens=0,
        total_output_tokens=0,
        total_tokens=0,
        total_duration_seconds=1.0,
        artifact_ids=["art-report"],
    )


def _review_run(
    inputs: Mapping[str, object] | None = None,
    workflow_type: WorkflowType = WorkflowType.REVIEW,
    execution_id: str = EXECUTION_ID,
    verdict: str = VERDICT,
) -> list[DomainEvent]:
    """The event stream one pr-review execution produces, in order."""
    return [
        _template(workflow_type),
        _started(
            inputs
            if inputs is not None
            else {"pr_number": PR, "repos": f"https://github.com/{REPO}"},
            execution_id,
        ),
        _artifact("investigate", "# What the change touches", "art-investigate", execution_id),
        _artifact("verify", "# Falsification attempts", "art-verify", execution_id),
        _artifact("report", verdict, "art-report", execution_id),
        _completed(execution_id),
    ]


async def _replay(
    publisher: ReviewVerdictPublisher, events: list[DomainEvent], start: int = 1
) -> None:
    """Feed events through the projection side only, as catch-up replay does."""
    checkpoints = MemoryCheckpointStore()
    for offset, event in enumerate(events):
        await publisher.handle_event(_envelope(event, start + offset), checkpoints)


def _publisher(conversation: FakeConversation | None) -> ReviewVerdictPublisher:
    return ReviewVerdictPublisher(InMemoryProjectionStore(), conversation=conversation)


@pytest.mark.unit
class TestVerdictReachesThePullRequest:
    """The verdict must exist as a comment, not only as an artifact."""

    async def test_completed_review_is_posted_to_its_pull_request(self) -> None:
        conversation = FakeConversation()
        publisher = _publisher(conversation)

        await _replay(publisher, _review_run())
        posted = await publisher.process_pending()

        assert posted == 1
        assert len(conversation.comments) == 1, (
            "the review completed and nothing reached the pull request -- this is #1097"
        )
        body = conversation.comments[0]
        assert VERDICT in body, "the comment does not carry the report phase's verdict"
        assert EXECUTION_ID in body
        assert HEAD_SHA[:8] in body, "the comment does not say which head it judged"

    async def test_only_the_final_phase_deliverable_is_published(self) -> None:
        """Earlier phases produce artifacts too; the verdict is the last one."""
        conversation = FakeConversation()
        publisher = _publisher(conversation)

        await _replay(publisher, _review_run())
        await publisher.process_pending()

        body = conversation.comments[0]
        assert "# Falsification attempts" not in body
        assert "# What the change touches" not in body


@pytest.mark.unit
class TestPostingIsIdempotent:
    """Re-running the processor must not stack duplicate verdicts."""

    async def test_second_pass_posts_nothing(self) -> None:
        conversation = FakeConversation()
        publisher = _publisher(conversation)
        await _replay(publisher, _review_run())

        first = await publisher.process_pending()
        second = await publisher.process_pending()

        assert (first, second) == (1, 0)
        assert len(conversation.comments) == 1

    async def test_rebuilt_projection_does_not_repost(self) -> None:
        """A projection rebuild replays every event; GitHub already holds the verdict."""
        conversation = FakeConversation()
        publisher = _publisher(conversation)
        await _replay(publisher, _review_run())
        await publisher.process_pending()

        rebuilt = _publisher(conversation)
        await _replay(rebuilt, _review_run())
        posted = await rebuilt.process_pending()

        assert posted == 0
        assert len(conversation.comments) == 1

    async def test_replay_alone_posts_nothing(self) -> None:
        """handle_event is the projection side: catch-up must not touch GitHub."""
        conversation = FakeConversation()

        await _replay(_publisher(conversation), _review_run())

        assert conversation.comments == []
        assert conversation.asked == []


@pytest.mark.unit
class TestReReviewIsSelfDescribing:
    """A second verdict on the same pull request says what it replaces."""

    async def test_new_head_supersedes_the_previous_verdict(self) -> None:
        conversation = FakeConversation()
        await _replay(_publisher(conversation), _review_run())
        first = _publisher(conversation)
        await _replay(first, _review_run())
        await first.process_pending()

        conversation.head = "abcdef1234567890abcdef1234567890abcdef12"
        second = _publisher(conversation)
        await _replay(
            second, _review_run(execution_id="exec-second", verdict="**Verdict.** Fixed.")
        )
        posted = await second.process_pending()

        assert posted == 1
        assert len(conversation.comments) == 2
        latest = conversation.comments[1]
        assert "**Verdict.** Fixed." in latest
        assert "abcdef12" in latest
        assert EXECUTION_ID in latest, "a re-review must name the verdict it supersedes"


@pytest.mark.unit
class TestNothingElseIsPublished:
    """Only review executions that named a pull request are published."""

    async def test_non_review_workflow_is_ignored(self) -> None:
        conversation = FakeConversation()
        publisher = _publisher(conversation)

        await _replay(publisher, _review_run(workflow_type=WorkflowType.IMPLEMENTATION))
        posted = await publisher.process_pending()

        assert posted == 0
        assert conversation.comments == []

    async def test_execution_without_a_pr_number_is_ignored(self) -> None:
        conversation = FakeConversation()
        publisher = _publisher(conversation)

        await _replay(publisher, _review_run(inputs={"repos": f"https://github.com/{REPO}"}))
        posted = await publisher.process_pending()

        assert posted == 0
        assert conversation.comments == []

    async def test_ambiguous_repository_is_ignored(self) -> None:
        """Two repos and one PR number: nothing can say which pull request."""
        conversation = FakeConversation()
        publisher = _publisher(conversation)

        await _replay(
            publisher,
            _review_run(
                inputs={
                    "pr_number": PR,
                    "repos": f"https://github.com/{REPO},https://github.com/syntropic137/other",
                }
            ),
        )
        posted = await publisher.process_pending()

        assert posted == 0
        assert conversation.comments == []

    async def test_unfinished_review_is_not_published(self) -> None:
        """A verdict is postable only once the execution has completed."""
        conversation = FakeConversation()
        publisher = _publisher(conversation)

        await _replay(publisher, _review_run()[:-1])
        posted = await publisher.process_pending()

        assert posted == 0
        assert conversation.comments == []

    async def test_no_github_app_posts_nothing_and_keeps_the_todo(self) -> None:
        """Unconfigured deployments must not crash the coordinator."""
        publisher = _publisher(None)

        await _replay(publisher, _review_run())

        assert await publisher.process_pending() == 0


@pytest.mark.unit
class TestPublisherIsWiredIntoTheCoordinator:
    """An unregistered ProcessManager never runs, however correct it is."""

    async def test_the_registered_publisher_posts_the_verdict(self) -> None:
        """Build the real coordinator registry and drive the publisher it holds.

        This is what production runs. A publisher that works in isolation but
        is missing from this list, or is built without the conversation port,
        leaves #1097 exactly as it was.
        """
        from typing import Any, cast

        from syn_adapters.subscriptions.coordinator_service import (
            create_coordinator_service,
        )

        conversation = FakeConversation()
        service = create_coordinator_service(
            event_store=cast("Any", object()),
            projection_store=InMemoryProjectionStore(),
            pr_conversation=conversation,
        )

        registered = [p for p in service._projections if isinstance(p, ReviewVerdictPublisher)]
        assert len(registered) == 1, "the coordinator does not run a ReviewVerdictPublisher"

        await _replay(registered[0], _review_run())
        assert await registered[0].process_pending() == 1
        assert VERDICT in conversation.comments[0]
