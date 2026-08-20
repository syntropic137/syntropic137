"""Turn a capture verdict into an observation, on the observability lane.

LANE 2, DELIBERATELY. Whether a transcript reached the central store has no
bearing on whether the workflow succeeded, and must never acquire one. If a
failed upload could fail an execution, the fail-open policy would be reversed
by the back door, quietly, by whoever wired it. So this writes telemetry and
returns; it touches no aggregate and raises nothing.

WHAT THE EXPECTATIONS ARE BUILT FROM. `CaptureExpectations` exists so a verdict
can be checked against where the caller MEANT the sessions to go, rather than
against whatever the exporter happened to be pointed at. Building it here, from
the same settings object that configured the workspace, is what makes that
check meaningful: both sides come from one source, so a mismatch is real
evidence rather than two guesses disagreeing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field

from syn_adapters.workspace_backends.agentic.capture_result import CaptureExpectations
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_adapters.workspace_backends.agentic.session_store_env import deployment_identity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_adapters.workspace_backends.agentic.capture_result import (
        AuthoritativeCapture,
    )
    from syn_shared.events import EventType
    from syn_shared.settings.session_store import SessionStoreSettings

__all__ = [
    "SESSION_CAPTURE_OBSERVATION",
    "CaptureObservationData",
    "ObservationWriter",
    "build_expectations",
    "record_capture_outcome",
]

logger = logging.getLogger(__name__)

#: Bumped on any incompatible change to the recorded payload.
_PAYLOAD_SCHEMA_VERSION: Final = 1

#: Telemetry gets a short, bounded slice of teardown. The write is already
#: failure-tolerant, but a hung connection pool would otherwise block a phase
#: that has finished its actual work.
_WRITE_TIMEOUT_SECONDS: Final = 5.0

#: The event type, taken from syn_shared, which is the single source of truth
#: gating the write path: a type the domain knows about and that Literal does
#: not is a write that fails validation at the point of recording. Importing
#: the DOMAIN enum here would invert layering, so the shared spelling is the
#: one both sides agree on.
SESSION_CAPTURE_OBSERVATION: Final[EventType] = "session_capture"


class CaptureObservationData(BaseModel):
    """The recorded shape of a capture verdict.

    A model rather than a dict literal because this is persisted and read back
    by things that are not this module: a dashboard, a query, and eventually a
    backfill pass deciding what to re-send. A field renamed by accident in a
    dict literal is a silent break at the far end; here it is a type error.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = _PAYLOAD_SCHEMA_VERSION
    """Bumped on any incompatible change, so a reader can refuse rather than
    misread a field whose meaning moved."""

    state: str
    needs_backfill: bool
    reason: str | None

    # OBSERVED: what the exporter said. Any of these can be None precisely when
    # something went wrong, which is when a backfill pass needs them most.
    store_url: str | None
    origin_environment: str | None
    origin_deployment: str | None
    counters: dict[str, int] = Field(default_factory=dict)

    # EXPECTED: what the host meant. Recorded separately because the observed
    # fields are missing or wrong in exactly the failures worth retrying, and a
    # backfill deciding where to re-send cannot use a value the failed run did
    # not produce.
    expected_store_url: str | None = None
    expected_deployment: str | None = None
    expected_sessions: bool | None = None

    partition: str | None = None
    """The spool partition this execution wrote to.

    What a retry needs to find the transcripts again. Note the spool is
    container-local today, so a post-teardown backfill cannot reach it: this
    field records the identity a durable archive will need, and does not by
    itself make backfill possible."""


class ObservationWriter(Protocol):
    """The observability lane's write side."""

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None: ...


def build_expectations(
    settings: SessionStoreSettings,
    app_environment: str,
    *,
    expect_sessions: bool,
) -> CaptureExpectations | None:
    """What this execution's capture SHOULD look like, or None if disabled.

    None when no store is configured, which is the overwhelmingly common case
    and not a problem. Returning None rather than an empty expectation keeps
    "capture is off" and "capture ran and told us nothing" distinguishable.

    `expect_sessions` is the caller's, because only the caller knows whether an
    agent actually ran. It is what stops a deleted spool reading as a clean
    sweep: an exporter that discovers nothing is honest, and only the caller can
    say whether nothing is the right answer.
    """
    if not settings.is_enabled or not settings.url:
        return None
    # .strip(), matching what session_store_env injects into the container.
    # The settings validator rejects a whitespace-only URL but does not trim a
    # valid one, so raw settings.url and the injected value can differ by
    # surrounding whitespace. That would compare unequal on every single
    # execution and report UNKNOWN forever: an indicator uniformly broken while
    # looking like it works.
    return CaptureExpectations(
        store_url=settings.url.strip(),
        deployment=deployment_identity(app_environment),
        expect_sessions=expect_sessions,
    )


async def record_capture_outcome(
    writer: ObservationWriter | None,
    outcome: AuthoritativeCapture,
    *,
    session_id: str,
    expectations: CaptureExpectations | None = None,
    partition: str | None = None,
    execution_id: str | None = None,
    phase_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    """Record one capture verdict. Never raises, and never blocks anything.

    DISABLED is not written. A deployment with no store configured would
    otherwise emit one of these per phase forever, which is noise that trains
    an operator to ignore the signal, and an indicator nobody reads is worth
    nothing.
    """
    if writer is None or outcome.state is CaptureState.DISABLED:
        return

    payload = CaptureObservationData(
        state=outcome.state.value,
        needs_backfill=outcome.needs_backfill,
        reason=outcome.reason,
        store_url=outcome.store_url,
        origin_environment=outcome.origin_environment,
        origin_deployment=outcome.origin_deployment,
        counters=dict(outcome.counters),
        expected_store_url=expectations.store_url if expectations else None,
        expected_deployment=expectations.deployment if expectations else None,
        expected_sessions=expectations.expect_sessions if expectations else None,
        partition=partition,
    )

    try:
        await asyncio.wait_for(
            writer.record_observation(
                session_id=session_id,
                observation_type=SESSION_CAPTURE_OBSERVATION,
                data=payload.model_dump(),
                execution_id=execution_id,
                phase_id=phase_id,
                workspace_id=workspace_id,
            ),
            timeout=_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # The observability lane is not allowed to break the run it observes.
        # Losing the record is bad; converting a successful phase into a failed
        # one because we could not write telemetry about it is worse.
        logger.warning("could not record session-capture observation: %s", exc)
