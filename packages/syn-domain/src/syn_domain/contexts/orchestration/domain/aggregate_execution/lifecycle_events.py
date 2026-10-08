"""The events an execution starts and ends with, built from their commands.

Kept out of the aggregate because they are payload assembly, not decisions:
the guard that decides whether a run may end this way stays on the handler,
and what these build is only what that decision records.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        CancelExecutionCommand,
        CompleteExecutionCommand,
        FailExecutionCommand,
        RecordCancelledWorkCommand,
        RecordPullRequestMergeCommand,
        StartExecutionCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        EvalBaselinePin,
        ReviewVerdict,
    )
    from syn_domain.contexts.orchestration.domain.events.CancelledWorkQuarantinedEvent import (
        CancelledWorkQuarantinedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
        ExecutionCancelledEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.PullRequestMergeRecordedEvent import (
        PullRequestMergeRecordedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
        WorkflowCompletedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
        WorkflowFailedEvent,
    )


def started_event(command: StartExecutionCommand) -> WorkflowExecutionStartedEvent:
    """The `WorkflowExecutionStarted` a fresh run records, pins included."""
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )

    return WorkflowExecutionStartedEvent(
        workflow_id=command.workflow_id,
        execution_id=command.aggregate_id,
        workflow_name=command.workflow_name,
        started_at=datetime.now(UTC),
        total_phases=command.total_phases,
        inputs=command.inputs,
        expected_completion_at=command.expected_completion_at,
        phase_definitions=(
            [asdict(pd) for pd in command.phase_definitions] if command.phase_definitions else None
        ),
        pinned_phases=command.pinned_phases,
        source_commits=command.source_commits,
        tags=list(command.tags),
        eval_id=None if command.launch_eval.eval_id is None else str(command.launch_eval.eval_id),
        eval_selection=(
            None
            if command.launch_eval.selection is EvalSelection.NONE
            else command.launch_eval.selection.value
        ),
        eval_baseline=_eval_baseline(command),
    )


def _eval_baseline(command: StartExecutionCommand) -> list[EvalBaselinePin] | None:
    """The admitted eval's frozen baseline, or None for a run in no eval."""
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        EvalBaselinePin,
    )

    launch = command.launch_eval
    if launch.eval_id is None:
        return None
    return [
        EvalBaselinePin(
            repository=pin.repository.slug,
            requested_ref=pin.requested_ref,
            commit_sha=pin.commit_sha,
        )
        for pin in launch.baseline
    ]


def completed_event(
    command: CompleteExecutionCommand,
    workflow_id: str,
    review_verdict: ReviewVerdict | None = None,
) -> WorkflowCompletedEvent:
    """The `WorkflowCompleted` a completed run records.

    ``review_verdict`` is the aggregate's, never the command's: how a run ended
    is read off its own stream, not taken from whoever asked it to end.
    """
    from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
        WorkflowCompletedEvent,
    )

    return WorkflowCompletedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        completed_at=datetime.now(UTC),
        total_phases=command.total_phases,
        completed_phases=command.completed_phases,
        total_input_tokens=command.total_input_tokens,
        total_output_tokens=command.total_output_tokens,
        total_cache_creation_tokens=command.total_cache_creation_tokens,
        total_cache_read_tokens=command.total_cache_read_tokens,
        total_tokens=(
            command.total_input_tokens
            + command.total_output_tokens
            + command.total_cache_creation_tokens
            + command.total_cache_read_tokens
        ),
        total_duration_seconds=command.duration_seconds,
        artifact_ids=command.artifact_ids,
        review_verdict=review_verdict,
    )


def failed_event(command: FailExecutionCommand, workflow_id: str) -> WorkflowFailedEvent:
    """The `WorkflowFailed` a failed run records."""
    from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
        WorkflowFailedEvent,
    )

    return WorkflowFailedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        failed_at=datetime.now(UTC),
        failed_phase_id=command.failed_phase_id,
        error_message=command.error,
        error_type=command.error_type,
        completed_phases=command.completed_phases,
        total_phases=command.total_phases,
        failed_phase_duration_seconds=command.failed_phase_duration_seconds,
        # list() rather than a default, and None rather than []: the event
        # has to preserve the difference between "read, and no branch had
        # moved" and "nobody could read it" (#1200).
        observed_branches=(
            None if command.observed_branches is None else list(command.observed_branches)
        ),
        # Straight through, None included: "nothing observed a status" is
        # a fact about the failure and coercing it to 0 would report a
        # clean exit for a phase nobody watched (#1319).
        exit_code=command.exit_code,
        failed_phase_artifact_ids=list(command.failed_phase_artifact_ids),
        quarantined_refs=list(command.quarantined),
        # Spread into four named fields HERE, once, rather than carried as
        # a nested object: every sibling `failed_phase_*` field on this
        # event is flat, and the projection that reads them reads flat
        # keys. The total is deliberately not a fifth field - it is derived
        # from these four wherever it is wanted, so it cannot disagree with
        # them (#1262).
        failed_phase_input_tokens=command.failed_phase_usage.input_tokens,
        failed_phase_output_tokens=command.failed_phase_usage.output_tokens,
        failed_phase_cache_creation_tokens=command.failed_phase_usage.cache_creation_tokens,
        failed_phase_cache_read_tokens=command.failed_phase_usage.cache_read_tokens,
        # Straight from the command, never re-derived here (#1357). The
        # only frame that could tell a correct refusal from a crash was the
        # one holding the phase's own verdict, several hops upstream; an
        # aggregate looking at `error_type` or at the message text would be
        # guessing, and guessing is what put the distinction in prose.
        failure_classification=command.classification,
        # Beside it, never instead of it (#1392). The classification is
        # what the platform measured; this is what the phase SAID, and the
        # event is where the two stop being one frame's local variables and
        # start being the record every read model is built from.
        reported_failure_reason=command.reported_failure_reason,
        upstream_failure_kind=command.upstream_failure_kind,
        # Typed, so a client selects on reason and delegate rather than
        # parsing `error` (#894).
        delegation_failure=command.delegation_failure,
    )


def cancelled_work_event(
    command: RecordCancelledWorkCommand, workflow_id: str
) -> CancelledWorkQuarantinedEvent:
    """The `CancelledWorkQuarantined` a cancelled run records for the refs its save landed."""
    from syn_domain.contexts.orchestration.domain.events.CancelledWorkQuarantinedEvent import (
        CancelledWorkQuarantinedEvent,
    )

    return CancelledWorkQuarantinedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        quarantined_at=datetime.now(UTC),
        quarantined_refs=list(command.quarantined),
    )


def merge_recorded_event(
    command: RecordPullRequestMergeCommand, workflow_id: str
) -> PullRequestMergeRecordedEvent:
    """The `PullRequestMergeRecorded` a contributing run records for a merged PR (#1728)."""
    from syn_domain.contexts.orchestration.domain.events.PullRequestMergeRecordedEvent import (
        PullRequestMergeRecordedEvent,
    )

    return PullRequestMergeRecordedEvent(
        execution_id=command.aggregate_id,
        workflow_id=workflow_id,
        repository=command.repository,
        pull_request=command.pull_request,
        merged_at=command.merged_at,
    )


def cancelled_event(command: CancelExecutionCommand, workflow_id: str) -> ExecutionCancelledEvent:
    """The `ExecutionCancelled` a cancelled run records."""
    from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
        ExecutionCancelledEvent,
    )

    return ExecutionCancelledEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=command.phase_id,
        cancelled_at=datetime.now(UTC),
        reason=command.reason,
    )
