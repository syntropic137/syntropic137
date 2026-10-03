"""A session that fails before the agent runs must still be observable.

Sessions that die in setup (missing setup.sh, unconfigured provider) recorded
SessionCompleted{failed} and NOTHING else, so they existed in the domain lane
and were invisible to observability. That left two different session counts -
one including failures, one including delegates, neither including both - and
no way to see a failed run on the dashboard at all.

The fix is not a smarter count. It is recording the fact that was missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from syn_domain.testing.fake_session_repository import FakeSessionRepository
from syn_shared.events import SESSION_COMPLETED, SESSION_ERROR, SESSION_SUMMARY


@dataclass(frozen=True)
class _Recorded:
    """One observation the manager wrote, captured for assertion."""

    session_id: str
    observation_type: str
    data: Mapping[str, object]
    execution_id: str | None
    phase_id: str | None


class _RecordingWriter:
    def __init__(self) -> None:
        self.observations: list[_Recorded] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: object,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.observations.append(
            _Recorded(
                session_id=session_id,
                observation_type=str(getattr(observation_type, "value", observation_type)),
                data=data,
                execution_id=execution_id,
                phase_id=phase_id,
            )
        )


def _manager(writer: _RecordingWriter | None):
    from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
        SessionLifecycleManager,
    )

    return SessionLifecycleManager(
        repository=FakeSessionRepository(),
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="setup",
        agent_provider="claude",
        agent_model="haiku",
        observability=writer,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_session_records_a_summary_observation() -> None:
    writer = _RecordingWriter()
    manager = _manager(writer)
    await manager.start()

    await manager.complete_failure(error_message="Setup phase failed: no setup.sh")

    errors = [o for o in writer.observations if o.observation_type == SESSION_ERROR]
    assert len(errors) == 1, "a failed session must leave an observable trace"
    data = errors[0].data
    assert data["status"] == "failed"
    assert "no setup.sh" in str(data["error_message"])

    # NEVER a session_summary. TimescaleSessionCostQuery selects the LATEST
    # summary (ORDER BY time DESC LIMIT 1), so a zero-token summary written at
    # failure time would supersede the real one for a session whose agent DID
    # run and then exited non-zero - reporting real work as free.
    assert [o for o in writer.observations if o.observation_type == SESSION_SUMMARY] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancelled_session_records_a_summary_observation() -> None:
    writer = _RecordingWriter()
    manager = _manager(writer)
    await manager.start()

    await manager.complete_cancelled(reason="user cancelled")

    errors = [o for o in writer.observations if o.observation_type == SESSION_ERROR]
    assert len(errors) == 1
    assert errors[0].data["status"] == "cancelled"
    assert [o for o in writer.observations if o.observation_type == SESSION_SUMMARY] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_session_records_a_completion_but_never_a_summary() -> None:
    """A successful phase leaves the same kind of trace a failed one does.

    THIS TEST CHANGED MEANING (#1034). It asserted `writer.observations == []`
    - no observation at all - under the name "no synthetic observation". The
    invariant it is named for, and the one the two tests above defend, is
    narrower than that: never a synthetic SESSION_SUMMARY, because
    TimescaleSessionCostQuery selects the latest summary and a second one
    would misprice the session. The blanket assertion also pinned the absence
    of the readable completion row, which is the bug: `complete_success` wrote
    its roll-up to Lane 1 under a name mapped to no observation type, so a
    successful session was countable in the domain lane and invisible on the
    timeline - the exact condition this module's docstring describes for
    failed sessions, left in place for successful ones.

    So the summary half is kept and tightened, and the absence half is
    replaced by the positive assertion it was hiding.
    """
    writer = _RecordingWriter()
    manager = _manager(writer)
    await manager.start()

    await manager.complete_success(
        input_tokens=10,
        output_tokens=20,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=30,
        duration_seconds=1.0,
        source="test",
    )

    # The invariant this test exists for, unchanged: nothing priceable is
    # synthesised here. The stream processors already wrote the real summary.
    assert [o for o in writer.observations if o.observation_type == SESSION_SUMMARY] == []

    # ...and the session is now visible on the timeline it ended on.
    completions = [o for o in writer.observations if o.observation_type == SESSION_COMPLETED]
    assert len(completions) == 1, "a successful session must leave an observable trace too"
    assert completions[0].execution_id == "exec-1"
    assert completions[0].phase_id == "setup"
    assert completions[0].data["duration_ms"] == 1000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_observability_is_optional() -> None:
    """Session tracking must not start depending on a recorder being wired."""
    manager = _manager(None)
    await manager.start()
    await manager.complete_failure(error_message="boom")
