"""Connecting a phase's capture verdict to the delegate import (#895).

Sits beside :mod:`phase_capture`, which produces the input this consumes: the
probe names the session ids the store confirmed, and this prices the ones the
platform did not already bill.

Separate from the processor because the processor is an orchestrator - it
decides what happens next - and this is a step. Keeping the payload shaping
here also keeps the domain module free of the telemetry schema.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from uuid import NAMESPACE_URL, UUID, uuid5

from syn_domain.contexts.agent_sessions import (
    ObservationType,
    import_phase_delegates,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_capture import (
    capture_phase_session,
)
from syn_shared.events import SESSION_SUMMARY
from syn_shared.pricing import price_tokens

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.agentic.capture_result import (
        AuthoritativeCapture,
    )
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service.managed_workspace import (
        ManagedWorkspace,
    )
    from syn_domain.contexts.agent_sessions import PricedUsage, SessionStorePort
    from syn_domain.contexts.agent_sessions.import_ledger import ImportLedgerPort
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
        StreamResult,
    )

logger = logging.getLogger(__name__)

#: Namespace for the coverage-gap marker. Fixed forever, and deliberately NOT
#: the delegate namespace: a marker must never be mistaken for a priced session.
_COVERAGE_GAP_NAMESPACE: Final[UUID] = uuid5(
    NAMESPACE_URL, "https://syntropic137.dev/delegate-coverage-gap"
)

__all__ = [
    "DelegateUsageRecorder",
    "capture_and_import_phase",
    "close_phase_workspaces",
    "remember_leader_native_id",
]


def _token_fields(usage: PricedUsage | None) -> Mapping[str, object]:
    """The four disjoint buckets, or zeroes when nothing could be priced.

    Two branches rather than a ternary per field: an unpriceable delegate is a
    different CASE, not five independent fallbacks, and writing it that way is
    what let a five-way conditional grow to complexity 17.
    """
    if usage is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "model": None,
        }
    return {
        "input_tokens": usage.uncached_input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "model": usage.model,
    }


def _summary_fields(usage: PricedUsage | None) -> Mapping[str, object]:
    """Summary totals under the names the cost projection reads.

    ``num_turns`` and ``duration_ms`` are explicitly None: a delegate is
    reconstructed from a stored transcript, never watched live, and 0 would
    read as "ran, took no time, took no turns".
    """
    base = {"num_turns": None, "duration_ms": None, "delegated": True}
    if usage is None:
        return {
            **base,
            "model": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }
    return {
        **base,
        "model": usage.model,
        "total_input_tokens": usage.uncached_input_tokens,
        "total_output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
    }


def _delegate_cost(usage: PricedUsage | None, session_id: str) -> float | None:
    """Price a delegate, or None when there is nothing priceable.

    Goes through ``price_tokens``, the documented single cost entry point, so
    the rate table stays the one authority and an unknown model produces a
    greppable warning rather than a silent zero.
    """
    if usage is None:
        return None
    priced = price_tokens(
        usage.model,
        usage.uncached_input_tokens,
        usage.output_tokens,
        cache_creation=usage.cache_creation_tokens,
        cache_read=usage.cache_read_tokens,
        context=f"delegate {session_id}",
    )
    if not priced.is_priced or priced.cost is None:
        return None
    return float(priced.cost)


def _coverage_gap_session_id(execution_id: str, phase_id: str) -> str:
    """A stable id for the marker recorded when the leader cannot be identified.

    Derived, not minted, so a phase re-processed after a crash addresses the
    same marker rather than accumulating one per attempt. Namespaced separately
    from delegate ids so it can never collide with a real session.
    """
    return str(uuid5(_COVERAGE_GAP_NAMESPACE, f"{execution_id}/{phase_id}"))


class DelegateUsageRecorder:
    """Shapes a recovered delegate cost into the observations the read path needs.

    Lives here rather than in the domain module because this is the layer that
    already knows the observation payload's field names. Keeping that knowledge
    on one side of the seam means a telemetry-schema rename breaks loudly here
    instead of silently unpricing delegates.
    """

    def __init__(self, writer: ObservabilityRecorder) -> None:
        self._writer = writer

    async def record_delegate_usage(
        self,
        *,
        session_id: str,
        usage: PricedUsage | None,
        unpriced_reason: str | None,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
    ) -> None:
        """Write BOTH observations a delegate needs to become visible.

        token_usage alone is not enough, and that is not obvious: verified on a
        live run, the delegate's token_usage landed perfectly and the execution
        total did not move by a cent. ExecutionCostProjection.on_session_summary
        is what adds cost; token_usage is only a fallback for sessions still in
        progress. A delegate has no summary of its own - it was never a platform
        session - so one is minted here.
        """
        # Present only when there IS a reason, so its presence alone marks a
        # delegate that could not be priced. Zeroes carrying a reason, never an
        # omission: a dropped delegate is indistinguishable from one that never
        # ran, which is the invisibility this whole issue is about.
        reason_field = {"unpriced_reason": unpriced_reason} if unpriced_reason else {}
        cost = _delegate_cost(usage, session_id)
        # Omitted when unpriceable, deliberately. The projection then counts the
        # delegate's TOKENS with no cost, which reads as a visible gap rather
        # than as work that was free.
        cost_field = {"total_cost_usd": cost} if cost is not None else {}

        for observation_type, fields in (
            (ObservationType.TOKEN_USAGE, {**_token_fields(usage), "delegated": True}),
            (SESSION_SUMMARY, {**_summary_fields(usage), **cost_field}),
        ):
            await self._writer.record_observation(
                session_id=session_id,
                observation_type=observation_type,
                data={**fields, **reason_field},
                execution_id=execution_id,
                phase_id=phase_id,
                workspace_id=workspace_id,
            )


class ImportDisposition(StrEnum):
    """How an import ended, for callers that must decide whether to retry.

    `import_delegates_for_phase` is deliberately fail-open: it must never turn
    agent work that succeeded into a phase that failed. But swallowing the
    exception also erased the DIFFERENCE between "imported" and "could not
    import", and the caller then discarded the leader identity either way -
    so the retry had nothing to distinguish the leader from its delegates and
    refused, dropping the phase's delegate cost. Fail-open needs a disposition,
    not silence.
    """

    COMPLETED = "completed"
    """The import ran. Nothing is owed; the leader identity can be released."""

    FAILED = "failed"
    """It raised. A retry may still succeed, so keep the leader identity."""

    SKIPPED = "skipped"
    """Nothing to import - no store, no writer, or no captured sessions."""


async def import_delegates_for_phase(
    capture: AuthoritativeCapture | None,
    *,
    session_store: SessionStorePort | None,
    writer: ObservabilityRecorder | None,
    leader_native_session_id: str | None,
    phase_id: str,
    execution_id: str,
    workspace_id: str | None = None,
    ledger: ImportLedgerPort | None = None,
) -> ImportDisposition:
    """Price the sessions this phase produced that nobody billed.

    Runs on the SAME two paths capture does - normal finalisation and
    teardown after a cancel or failure - because a phase that was cancelled
    still ran delegates, and their cost is exactly as real as a completed
    phase's. Carving that out would leave a class of executions quietly
    understated.

    Fail-open, like capture: an import that cannot run leaves the phase's
    own cost intact and unchanged. It must never turn agent work that
    succeeded into a phase that failed.
    """
    # Both are optional on the processor, so they are checked rather than
    # assumed: with no store there is nothing to read and with no writer there
    # is nowhere to record it, and calling through would raise inside a
    # teardown path that must not fail a phase.
    if session_store is None or writer is None or capture is None:
        return ImportDisposition.SKIPPED

    captured_ids = capture.agent_session_ids or ()
    if not captured_ids:
        return ImportDisposition.SKIPPED

    try:
        outcome = await import_phase_delegates(
            session_store,
            DelegateUsageRecorder(writer),
            leader_native_session_id=leader_native_session_id,
            captured_session_ids=captured_ids,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
            # One pass here. The sweep already CONFIRMED these sessions
            # reached the store, so a read that misses is a race measured
            # in tenths of a second rather than a wait worth holding a
            # phase open for; anything still unreadable is written as a
            # named gap instead.
            attempts_remaining=0,
            # None means no ledger is wired, and the caller then keeps the
            # cross-phase and re-import double counts (#933, #936). Passing it
            # is the point; it is optional only so call sites can migrate
            # independently of the durable adapter (#938).
            ledger=ledger,
        )
    except Exception:
        logger.exception(
            "Delegate import failed for phase %s; phase cost stands unchanged", phase_id
        )
        return ImportDisposition.FAILED

    if outcome.leader_missing_from_sweep:
        # A LOG IS NOT A SIGNAL. Without a durable record the phase reports a
        # total that looks complete while delegates it captured went unpriced -
        # the "undercount that looks finished" this module exists to prevent.
        #
        # Zero tokens and no model: contributes no cost, and prices as UNPRICED,
        # so ExecutionCostProjection increments unpriced_observation_count and
        # unpriced_by_phase. The API already renders that as incomplete
        # coverage rather than as a phase that spent nothing (#890).
        await writer.record_observation(
            session_id=_coverage_gap_session_id(execution_id, phase_id),
            observation_type=ObservationType.TOKEN_USAGE,
            data={
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "model": None,
                "delegated": True,
                "coverage_incomplete": True,
                "captured_session_count": len(captured_ids),
                "unpriced_reason": (
                    "the phase's own leader session id is not among the captured "
                    "ids, so delegates cannot be told from the leader"
                ),
            },
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )

        # Loud on purpose. The leader's id came off its own stream and the
        # sweep confirmed the session set, so a mismatch means one of those
        # two contracts moved - and every id is then a candidate, so
        # importing anything would risk billing the leader twice.
        logger.error(
            "Delegate import refused for phase %s: the leader's session id is not among "
            "the %d captured ids, so delegates cannot be told from the leader. "
            "No delegate cost was imported for this phase.",
            phase_id,
            len(captured_ids),
        )
        # COMPLETED, not FAILED: the import ran and recorded a durable coverage
        # gap. Retrying would re-record the same gap, not recover the cost.
        return ImportDisposition.COMPLETED

    if outcome.imported:
        logger.info(
            "Imported %d delegate session(s) for phase %s (%d priced)",
            len(outcome.imported),
            phase_id,
            sum(1 for d in outcome.imported if d.priced),
        )
    return ImportDisposition.COMPLETED


async def capture_and_import_phase(
    capture_port: SessionCapturePort | None,
    workspace: ManagedWorkspace | None,
    *,
    session_store: SessionStorePort | None,
    writer: ObservabilityRecorder | None,
    leader_native_ids: dict[tuple[str, str], str],
    session_id: str,
    phase_id: str,
    ledger: ImportLedgerPort | None = None,
) -> None:
    """Probe for this phase's sessions, then price the ones nobody billed.

    Takes the leader MAP rather than a resolved id, and discards from it, so
    the (execution_id, phase_id) key convention lives in one module instead of
    at every call site. Discarding means a completed phase leaves nothing for a
    later run of the same phase id to pick up.

    The discard happens only AFTER the import succeeds. Popping first made the
    identity unrecoverable the moment anything downstream raised: the retry ran
    with no leader, so it could not tell the leader from its delegates and took
    the refusal path, dropping the phase's delegate cost entirely. Surviving a
    process RESTART is a different problem - the map is in memory - and stays
    open as part of #933.

    One function because the two are one step with one ordering rule: both must
    happen while the container is still up. The processor calls this from the
    finalise path AND the cancel/failure path, and having a single entry point
    is what stops those two drifting - a cancelled phase that skipped the
    import would be understated in a way nothing downstream could detect.
    """
    execution_id = getattr(workspace, "execution_id", "") or ""
    leader_native_session_id = leader_native_ids.get((execution_id, phase_id))
    capture = await capture_phase_session(
        capture_port, workspace, session_id=session_id, phase_id=phase_id
    )
    disposition = await import_delegates_for_phase(
        capture,
        session_store=session_store,
        writer=writer,
        leader_native_session_id=leader_native_session_id,
        phase_id=phase_id,
        execution_id=execution_id,
        # ManagedWorkspace names this workspace_id. `id` silently returned
        # None on every call, so every delegate observation lost its
        # workspace linkage - invisible because getattr has a default.
        workspace_id=getattr(workspace, "workspace_id", None),
        ledger=ledger,
    )
    if disposition is not ImportDisposition.FAILED:
        leader_native_ids.pop((execution_id, phase_id), None)


async def close_phase_workspaces(
    context: str,
    *,
    workspace_cms: dict[str, AbstractAsyncContextManager[ManagedWorkspace]],
    workspaces: dict[str, ManagedWorkspace],
    session_ids: dict[tuple[str, str], str],
    leader_native_ids: dict[tuple[str, str], str],
    capture_port: SessionCapturePort | None,
    session_store: SessionStorePort | None,
    writer: ObservabilityRecorder | None,
    ledger: ImportLedgerPort | None = None,
) -> None:
    """Probe, import, then tear down every still-open phase workspace.

    The cancel and failure path. A phase that never reached finalisation still
    ran an agent, and a failed run is the one whose transcript is most worth
    having - so the probe and the import both happen here too, in the same
    order and before the container goes away.

    ``session_ids`` is keyed (execution_id, phase_id), like ``leader_native_ids``
    (#1044): a phase-only key would let a concurrently running execution's
    session id answer this lookup. Left uncleared here (unlike ``workspace_cms``
    and ``leader_native_ids``, which this function owns exclusively) - the
    caller clears only the current execution's own entries, since this
    processor is shared across concurrent executions and a blanket clear would
    erase another execution's still-live session ids.
    """
    for phase_id, workspace_cm in list(workspace_cms.items()):
        workspace = workspaces.get(phase_id)
        execution_id = getattr(workspace, "execution_id", "") or ""
        await capture_and_import_phase(
            capture_port,
            workspace,
            session_store=session_store,
            writer=writer,
            leader_native_ids=leader_native_ids,
            session_id=session_ids.get((execution_id, phase_id), ""),
            phase_id=phase_id,
            ledger=ledger,
        )
        try:
            await workspace_cm.__aexit__(None, None, None)
        except Exception:
            logger.exception("Error cleaning up workspace during %s", context)

    workspace_cms.clear()
    leader_native_ids.clear()


def remember_leader_native_id(
    leader_native_ids: dict[tuple[str, str], str],
    key: tuple[str, str],
    stream_result: StreamResult,
) -> None:
    """Record the id this phase's own harness announced, if it announced one.

    ``key`` is (execution_id, phase_id). Phase id alone is NOT unique: the
    processor is shared across concurrent dispatches, so two runs of the same
    workflow would overwrite each other's leader and each could then subtract
    a session that is not in its own sweep.

    A blank or absent id is not stored. Storing one would make every phase that
    announced nothing share a key, and the import would subtract the wrong
    session from the sweep.
    """
    announced = stream_result.leader_native_session_id
    if announced:
        leader_native_ids[key] = announced
