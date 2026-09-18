"""Projection for workflow execution detail view.

This projection maintains detailed execution state including per-phase metrics.
It's updated by WorkflowExecutionStarted, PhaseStarted, PhaseCompleted,
WorkflowCompleted, and WorkflowFailed events.

Uses AutoDispatchProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.phase_detail import (
    PhaseDetail,
)
from syn_shared.display import compute_duration_seconds

#: Totals a completion event MAY restate. Accumulated from PhaseCompleted
#: otherwise; see the zero-guard where these are applied.
logger = logging.getLogger(__name__)

#: Totals a completion event restates. These are REQUIRED final summary values
#: on WorkflowCompletedEvent, so 0 / 0.0 / [] are legitimate rather than "not
#: provided" -- the event is authoritative and overwrites.
_OPTIONAL_FIELD_NAMES = (
    "total_input_tokens",
    "total_output_tokens",
    "total_cache_creation_tokens",
    "total_cache_read_tokens",
    "total_duration_seconds",
    "artifact_ids",
)

#: The ONE field where a zero is known to be wrong rather than authoritative
#: (#969). Measured live: the phase reported 33.004841s while the completion
#: event carried 0.0, and token totals in the SAME event were correct. A zero
#: duration alongside phases that reported real time is self-contradictory.
#:
#: Deliberately NOT a general truthiness rule. `artifact_ids` is a list where
#: empty can be the correct final state, and the token totals are genuinely
#: authoritative; a blanket guard would contradict the event contract and
#: defeat future corrections.
_ZERO_IS_SUSPECT = "total_duration_seconds"


#: Phase statuses that mean "this phase had not finished". Only these are
#: closed out when a run is cancelled or interrupted; anything else already
#: recorded its own outcome and must not be rewritten.
_IN_FLIGHT_PHASE_STATUSES = frozenset({"running", "pending"})


class WorkflowExecutionDetailProjection(AutoDispatchProjection):
    """Builds workflow execution detail read model from events.

    This projection maintains detailed execution state including:
    - Overall execution status and metrics
    - Per-phase execution details with individual metrics
    - Artifact references

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_execution_details"
    VERSION = 11  # Bumped: per-phase timeout budgets are now recorded (#1262)

    def __init__(self, store: ProjectionStore):
        """Initialize with a projection store.

        Args:
            store: A ProjectionStore implementation
        """
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    @staticmethod
    def _find_phase(
        phases: list[dict[str, Any]], phase_id: str
    ) -> tuple[int, dict[str, Any]] | None:
        """Find a phase by ID, returning (index, phase_dict) or None."""
        for i, p in enumerate(phases):
            if p.get("phase_id") == phase_id:
                return i, p
        return None

    @staticmethod
    def _aggregate_totals(
        detail: dict[str, Any],
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        duration: float,
    ) -> None:
        """Add phase metrics to execution totals."""
        detail["total_input_tokens"] = detail.get("total_input_tokens", 0) + input_tokens
        detail["total_output_tokens"] = detail.get("total_output_tokens", 0) + output_tokens
        detail["total_cache_creation_tokens"] = (
            detail.get("total_cache_creation_tokens", 0) + cache_creation_tokens
        )
        detail["total_cache_read_tokens"] = (
            detail.get("total_cache_read_tokens", 0) + cache_read_tokens
        )
        detail["total_duration_seconds"] = detail.get("total_duration_seconds", 0.0) + duration

    @staticmethod
    def _completed_phases_after(event_data: dict, accumulated: int) -> int:
        """The count a terminal event states, or the accumulation if it is silent.

        A run that ends states how many phases it got through, and that figure
        is authoritative over the one accumulated from PhaseCompleted -- the
        accumulation misses any phase whose completion this projection never
        saw. Same precedence the list projection applies to the same field
        (#1147), which is what keeps the two views agreeing.
        """
        stated = event_data.get("completed_phases")
        return accumulated if stated is None else int(stated)

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted event.

        Creates a new execution detail with pending phases.
        """
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        # Extract repos from inputs field (ADR-058: stored as comma-separated string)
        repos_raw = event_data.get("inputs", {}).get("repos", "")
        repos = [u.strip() for u in str(repos_raw).split(",") if u.strip()] if repos_raw else []

        # Each phase's wall-clock budget, keyed by phase id. Stated once, on
        # this event, and not restated by the phase that later consumes it, so
        # it is read here and held on the execution record until
        # `on_phase_started` has a phase to attach it to (#1262). The store IS
        # this projection's memory; a map on the instance would not survive a
        # restart mid-run.
        #
        # DELIBERATELY NOT A HELPER, and please do not extract it. A function a
        # handler hands its payload to must declare a typed payload
        # (test_typed_projection_handlers.py, #1268), and there is no narrower
        # type to give this one: `event_data` is a `model_dump()` of an event
        # whose `phase_definitions` is itself `list[dict[str, Any]]`. Extracting
        # it adds a new untyped site to a table that only ever shrinks, so the
        # tidier-looking version is the one that fails the gate. It moves out of
        # here when the dispatch hands handlers the event itself.
        #
        # Every value is checked because none of them are validated: the field
        # is a list of `dict[str, Any]`, so a definition can carry anything at
        # all. A phase with no stated budget is absent rather than 0, which is
        # what keeps an unknown budget reading as None downstream instead of as
        # a number nobody set.
        definitions = event_data.get("phase_definitions")
        phase_budgets: dict[str, int] = {}
        for definition in definitions if isinstance(definitions, list) else []:
            if not isinstance(definition, dict):
                continue
            phase_id = definition.get("phase_id")
            timeout = definition.get("timeout_seconds")
            if isinstance(phase_id, str) and phase_id and isinstance(timeout, int):
                phase_budgets[phase_id] = timeout

        # Create initial phases from workflow definition (all pending)
        # Note: In a full implementation, we'd get phase names from workflow
        # For now, phases are populated as they start/complete
        detail = {
            "execution_id": execution_id,
            "workflow_id": event_data.get("workflow_id", ""),
            "workflow_name": event_data.get("workflow_name", ""),
            "status": "running",
            "started_at": event_data.get("started_at"),
            "completed_at": None,
            "phases": [],  # Populated as phases start/complete
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_creation_tokens": 0,
            "total_cache_read_tokens": 0,
            "total_duration_seconds": 0.0,
            "artifact_ids": [],
            "error_message": None,
            "repos": repos,
            # How many phases this run set out to do, and how many it has done.
            # Read off the SAME event the list projection reads them off, so a
            # run cannot report three phases in one view and one in the other
            # (#1147). total_phases is required on the event, so there is no
            # default worth defending here; 0 would be a run with no phases.
            "total_phases": event_data.get("total_phases", 0),
            "completed_phases": 0,
            # Held here, not served from here: `on_phase_started` moves each
            # budget onto the phase that it belongs to, which is where a
            # reader needs it next to that phase's elapsed time (#1262).
            "phase_budgets": phase_budgets,
        }
        await self._store.save(self.PROJECTION_NAME, execution_id, detail)

    async def on_phase_started(self, event_data: dict) -> None:
        """Handle PhaseStarted event.

        Adds a new phase entry with 'running' status.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        phase_id = event_data.get("phase_id", "")
        phases = existing.get("phases", [])

        if self._find_phase(phases, phase_id) is None:
            budgets = existing.get("phase_budgets") or {}
            phase = PhaseDetail.running(
                phase_id=phase_id,
                name=event_data.get("phase_name", phase_id),
                session_id=event_data.get("session_id"),
                started_at=event_data.get("started_at"),
                timeout_seconds=budgets.get(phase_id),
            )
            phases.append(phase.to_dict())
            existing["phases"] = phases
            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    @staticmethod
    def _update_phase_metrics(phase: dict[str, Any], event_data: dict) -> None:
        """Apply completion metrics from event data onto a phase dict."""
        phase["status"] = "completed"
        if event_data.get("session_id"):
            phase["session_id"] = event_data["session_id"]
        phase["artifact_id"] = event_data.get("artifact_id")
        phase["input_tokens"] = event_data.get("input_tokens", 0)
        phase["output_tokens"] = event_data.get("output_tokens", 0)
        phase["cache_creation_tokens"] = event_data.get("cache_creation_tokens", 0)
        phase["cache_read_tokens"] = event_data.get("cache_read_tokens", 0)
        phase["total_tokens"] = event_data.get("total_tokens", 0)
        # No default: a completion event that carried no elapsed time leaves the
        # duration unknown, and writing 0.0 would record a measurement nobody
        # made. The API boundary derives one from the timestamps instead.
        phase["duration_seconds"] = event_data.get("duration_seconds")
        phase["completed_at"] = event_data.get("completed_at")
        # The phase already exists here - started, then completed - so this is
        # the path virtually every real completion takes, and the path a
        # salvage takes. `PhaseDetail.completed` below handles the other one;
        # omitting it here is how the flag would have reached the store only
        # for phases whose PhaseStarted was never projected (#1300).
        phase["deliverable_recovered"] = bool(event_data.get("deliverable_recovered", False))

    @staticmethod
    def _track_artifact(existing: dict[str, Any], artifact_id: str | None) -> None:
        """Add an artifact ID to the execution detail if not already tracked."""
        if not artifact_id:
            return
        artifact_ids = existing.get("artifact_ids", [])
        if artifact_id not in artifact_ids:
            artifact_ids.append(artifact_id)
        existing["artifact_ids"] = artifact_ids

    async def on_phase_completed(self, event_data: dict) -> None:
        """Handle PhaseCompleted event.

        Updates phase with completion status and metrics.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        phase_id = event_data.get("phase_id")
        phases = existing.get("phases", [])

        found = self._find_phase(phases, phase_id or "")
        if found:
            _, phase = found
            self._update_phase_metrics(phase, event_data)
        else:
            budgets = existing.get("phase_budgets") or {}
            new_phase = PhaseDetail.completed(
                phase_id or "",
                phase_id or "",
                event_data,
                timeout_seconds=budgets.get(phase_id or ""),
            )
            phases.append(new_phase.to_dict())

        # Aggregate totals
        input_tokens = event_data.get("input_tokens", 0)
        output_tokens = event_data.get("output_tokens", 0)
        cache_creation_tokens = event_data.get("cache_creation_tokens", 0)
        cache_read_tokens = event_data.get("cache_read_tokens", 0)
        duration = event_data.get("duration_seconds", 0.0)
        self._aggregate_totals(
            existing,
            input_tokens,
            output_tokens,
            cache_creation_tokens,
            cache_read_tokens,
            duration,
        )

        self._track_artifact(existing, event_data.get("artifact_id"))
        existing["completed_phases"] = existing.get("completed_phases", 0) + 1

        existing["phases"] = phases
        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Handle WorkflowCompleted event.

        Marks execution as completed with final metrics.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "completed"
        existing["completed_at"] = event_data.get("completed_at")
        existing["completed_phases"] = self._completed_phases_after(
            event_data, existing.get("completed_phases", 0)
        )

        # Update with final totals from event if provided.
        #
        # A ZERO DURATION never overwrites a non-zero accumulation (#969); every
        # other field here stays authoritative. The totals are
        # are accumulated from PhaseCompleted events -- each one an observation of
        # work that actually happened. A completion event claiming 0 while phases
        # reported 33s is self-contradictory, and the accumulated value is the one
        # backed by evidence.
        #
        # Observed on a live run: the phase reported duration_seconds 33.004841,
        # the execution reported total_duration_seconds 0.0, because this loop
        # replaced the correct sum with the event's zero. Tokens survived the same
        # run, so the event carries some real totals and some empty ones -- which
        # is exactly the case a blind overwrite handles worst.
        for field in _OPTIONAL_FIELD_NAMES:
            if field not in event_data:
                continue
            incoming = event_data[field]
            if field == _ZERO_IS_SUSPECT and not incoming and existing.get(field):
                logger.warning(
                    "Ignoring empty %s in completion event for %s; keeping accumulated %s",
                    field,
                    execution_id,
                    existing[field],
                )
                continue
            existing[field] = incoming

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Handle WorkflowFailed event.

        Marks execution as failed with error information.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        kept_artifact_ids = event_data.get("failed_phase_artifact_ids") or []

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            # Create minimal entry for orphaned failure events (#598)
            existing = {
                "execution_id": execution_id,
                "workflow_id": event_data.get("workflow_id", ""),
                "workflow_name": event_data.get("workflow_name", ""),
                "status": "failed",
                "started_at": event_data.get("started_at"),
                "completed_at": event_data.get("failed_at"),
                "phases": [],
                "total_input_tokens": event_data.get("total_input_tokens", 0),
                "total_output_tokens": event_data.get("total_output_tokens", 0),
                "total_duration_seconds": 0.0,
                "artifact_ids": [],
                "error_message": event_data.get("error_message"),
                "completed_phases": event_data.get("completed_phases", 0),
                "total_phases": event_data.get("total_phases", 0),
            }
        else:
            existing["status"] = "failed"
            existing["completed_at"] = event_data.get("failed_at")
            existing["error_message"] = event_data.get("error_message")
            existing["completed_phases"] = self._completed_phases_after(
                event_data, existing.get("completed_phases", 0)
            )

        # Stamping the failed phase sits HERE, at depth 0, rather than inside
        # the `else` above. The orphan entry built in the other branch carries
        # an empty `phases` list, so the lookup finds nothing there and does
        # nothing - the case does not need a branch of its own, and giving it
        # one cost every field below three levels of nesting to be read under.
        failed_phase_id = event_data.get("failed_phase_id")
        found = (
            self._find_phase(existing.get("phases", []), failed_phase_id)
            if failed_phase_id
            else None
        )
        if found:
            _, phase = found
            phase["status"] = "failed"
            phase["error_message"] = event_data.get("error_message")

            # How this phase's branches stood when it died (#1200).
            # Copied verbatim INCLUDING None and []: the two are different
            # incidents - nobody could read the workspace, versus read it and
            # found no branch differing from how the phase found it - and a
            # `or []` here would report the first as the second. Absent on
            # every event that predates the field, which is null: correct,
            # because nothing looked.
            phase["observed_branches"] = event_data.get("observed_branches")

            # What this phase wrote and got to keep (#1321). A failed phase
            # always read artifact_id=None here, because the only thing that
            # ever set it was PhaseCompleted - so the one field an operator
            # looks at to find a refused phase's deliverable was the one field
            # guaranteed to be empty. First, matching the success path:
            # PhaseDetail names one artifact and the primary deliverable is
            # stored first.
            if kept_artifact_ids:
                phase["artifact_id"] = kept_artifact_ids[0]

            # What this phase spent before it died (#1262). The failed phase
            # never gets a PhaseCompleted event, which is the ONLY thing that
            # ever wrote these keys -- so every failed phase this projection
            # has ever stored reports zero tokens, and the record an operator
            # opens cannot tell a phase that stalled at 735 tokens from one
            # killed mid-work at 300k. Both say exit 124.
            #
            # Stamped unconditionally, zeros included, because zero is the
            # correct report for a phase whose agent never launched and is not
            # a "not provided" to be skipped over. The total is summed from the
            # four rather than carried as a fifth event field, so it cannot
            # disagree with them.
            failed_input = event_data.get("failed_phase_input_tokens", 0)
            failed_output = event_data.get("failed_phase_output_tokens", 0)
            failed_cache_creation = event_data.get("failed_phase_cache_creation_tokens", 0)
            failed_cache_read = event_data.get("failed_phase_cache_read_tokens", 0)
            phase["input_tokens"] = failed_input
            phase["output_tokens"] = failed_output
            phase["cache_creation_tokens"] = failed_cache_creation
            phase["cache_read_tokens"] = failed_cache_read
            phase["total_tokens"] = (
                failed_input + failed_output + failed_cache_creation + failed_cache_read
            )

            # The failed phase never gets a PhaseCompleted event, so without
            # this its duration_seconds is stuck at the 0.0
            # PhaseDetail.running() seeded it with -- reporting a timed-out
            # phase as instantaneous (#1036). The processor computes this from
            # when the phase actually started, so it is present exactly when a
            # phase was in flight.
            failed_duration = event_data.get("failed_phase_duration_seconds")
            if failed_duration is not None:
                phase["duration_seconds"] = failed_duration
                phase["completed_at"] = event_data.get("failed_at")

            # ONE roll-up for both, where before it was the duration alone: the
            # execution totals only accumulate from PhaseCompleted, so they
            # under-report by exactly the failed phase's time AND by exactly
            # what it spent. `or 0.0` because a failure with no phase in flight
            # has no duration to add, and adding nothing is the right answer
            # rather than a reason to skip the tokens too.
            self._aggregate_totals(
                existing,
                failed_input,
                failed_output,
                failed_cache_creation,
                failed_cache_read,
                failed_duration or 0.0,
            )

        # Outside the phase lookup, and outside the orphan branch above, on
        # purpose: an artifact that was stored exists whether or not this
        # projection can still find the phase it came from, and an execution
        # whose artifact_ids stay empty is one whose deliverable nothing links
        # to (#1321).
        for artifact_id in kept_artifact_ids:
            self._track_artifact(existing, artifact_id)

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    def _stamp_terminal_phase(
        self,
        existing: dict,
        phase_id: str | None,
        status: str,
        ended_at: datetime | str | None,
    ) -> None:
        """Close out the in-flight phase when a run ends without completing it.

        Cancellation and interruption set the phase's status and nothing else,
        so its duration_seconds stayed at the 0.0 that ``PhaseDetail.running()``
        seeded. A phase cancelled after 400 seconds reported 0.0 - the same
        "reported value that is not a measurement" defect as the frozen running
        duration this change exists to fix, and it is not hypothetical: six runs
        were cancelled mid-flight on 2026-09-01 and every one of them reports
        0.0.

        Same treatment the failed-phase path already gets (#1036), except the
        duration is computed here because cancel and interrupt events carry a
        timestamp rather than an elapsed time.
        """
        if not phase_id:
            return
        found = self._find_phase(existing.get("phases", []), phase_id)
        if not found:
            return
        _, phase = found

        # Only an IN-FLIGHT phase is closed out here. Guarding on lifecycle
        # status rather than on duration truthiness: a completed phase whose
        # measured duration is legitimately 0.0 would otherwise be recomputed
        # as the whole elapsed time and added to the execution total a second
        # time. Using `if not duration_seconds` to mean "still running" makes a
        # real measurement of zero indistinguishable from an absent one, which
        # is the same conflation this whole change exists to remove.
        if phase.get("status") not in _IN_FLIGHT_PHASE_STATUSES:
            return

        phase["status"] = status
        if phase.get("completed_at") is None:
            phase["completed_at"] = ended_at
        elapsed = compute_duration_seconds(phase.get("started_at"), now=ended_at)
        if elapsed is not None:
            phase["duration_seconds"] = elapsed
            self._aggregate_totals(existing, 0, 0, 0, 0, elapsed)

    async def on_execution_cancelled(self, event_data: dict) -> None:
        """Handle ExecutionCancelled event.

        Marks execution as cancelled via control plane.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "cancelled"
        existing["completed_at"] = event_data.get("cancelled_at")
        existing["error_message"] = event_data.get("reason") or "Cancelled by user"

        self._stamp_terminal_phase(
            existing, event_data.get("phase_id"), "cancelled", event_data.get("cancelled_at")
        )

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        """Handle WorkflowInterrupted event.

        Marks execution as interrupted (forceful stop via SIGINT) and captures
        the git SHA at the time of interruption.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "interrupted"
        existing["completed_at"] = event_data.get("interrupted_at")
        existing["error_message"] = event_data.get("reason") or "Interrupted by user"
        existing["git_sha"] = event_data.get("git_sha")

        self._stamp_terminal_phase(
            existing, event_data.get("phase_id"), "interrupted", event_data.get("interrupted_at")
        )

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionDetail | None:
        """Get execution detail by ID.

        Args:
            execution_id: The execution ID.

        Returns:
            Execution detail or None if not found.
        """
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if data:
            return WorkflowExecutionDetail.from_dict(data)
        return None
