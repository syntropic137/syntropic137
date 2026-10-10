"""A phase's workspace usage is recorded after teardown, on every path (#1310).

Usage is measured AS the workspace is destroyed and handed back on the
`ManagedWorkspace` by `create_workspace`'s `finally`. So the only correct moment
to write it is after `__aexit__`: a writer that ran before would always see
None. The doubles below set `teardown_usage` inside `__aexit__` exactly as the
service does, so a call placed before teardown records nothing and fails here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.agent_sessions import ObservationType
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    WorkspaceUsage,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import import (
    record_workspace_usage,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

pytestmark = pytest.mark.unit

PHASE = "p-usage"
SESSION = "s-usage"
USAGE = WorkspaceUsage(
    cpu_usage_seconds=12.5,
    cpu_throttled_seconds=0.75,
    nr_throttled=3,
    memory_peak_bytes=734_003_200,
    oom_kills=1,
    disk_bytes_at_teardown=52_428_800,
    delete_failures=("/ws/.git/objects/pack/locked.pack",),
    net_rx_bytes=1_048_576,
    net_tx_bytes=65_536,
)


LIFETIME_SECONDS = 600.0


@dataclass(frozen=True)
class _Aggregate:
    """The two lifecycle facts the usage row reads (#1716)."""

    terminated_at: datetime | None = datetime(2026, 10, 8, tzinfo=UTC)
    lifetime_seconds: float | None = LIFETIME_SECONDS


class _Workspace:
    execution_id = "e-usage"
    workspace_id = "w-usage"

    def __init__(self, aggregate: _Aggregate | None = None) -> None:
        self.teardown_usage: WorkspaceUsage | None = None
        self.aggregate = aggregate or _Aggregate()


class _WorkspaceCm:
    """Sets the usage during teardown, as `WorkspaceService.create_workspace` does."""

    def __init__(self, workspace: _Workspace) -> None:
        self._workspace = workspace

    async def __aenter__(self) -> object:
        return self._workspace

    async def __aexit__(self, *_exc: object) -> bool:
        self._workspace.teardown_usage = USAGE
        return False


@dataclass(frozen=True)
class _Row:
    session_id: str
    observation_type: ObservationType | str
    data: object
    execution_id: str | None
    phase_id: str | None
    workspace_id: str | None


class _Writer:
    def __init__(self, *, fail: BaseException | None = None) -> None:
        self.rows: list[_Row] = []
        self._fail = fail

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if self._fail is not None:
            raise self._fail
        self.rows.append(
            _Row(session_id, observation_type, data, execution_id, phase_id, workspace_id)
        )

    def usage_rows(self) -> list[_Row]:
        return [
            r for r in self.rows if r.observation_type == ObservationType.WORKSPACE_RESOURCE_USAGE
        ]


def _runtime(writer: _Writer) -> PhaseRuntime:
    runtime = PhaseRuntime(capture_port=None, session_store=None, writer=writer, ledger=None)
    workspace = _Workspace()
    runtime.attach_workspace(
        PHASE,
        workspace=cast("ManagedWorkspace", workspace),
        workspace_cm=cast("AbstractAsyncContextManager[ManagedWorkspace]", _WorkspaceCm(workspace)),
        agent_env={},
        claude_cmd=[],
        delivers_repo_changes=False,
    )
    runtime.launch(PHASE, session_id=SESSION)
    return runtime


def _assert_one_row(writer: _Writer) -> None:
    assert writer.usage_rows() == [
        _Row(
            session_id=SESSION,
            observation_type=ObservationType.WORKSPACE_RESOURCE_USAGE,
            data={
                "cpu_usage_seconds": 12.5,
                "cpu_throttled_seconds": 0.75,
                "nr_throttled": 3,
                "memory_peak_bytes": 734_003_200,
                "oom_kills": 1,
                "disk_bytes_at_teardown": 52_428_800,
                "delete_failures": ("/ws/.git/objects/pack/locked.pack",),
                "net_rx_bytes": 1_048_576,
                "net_tx_bytes": 65_536,
                "workspace_lifetime_seconds": LIFETIME_SECONDS,
            },
            execution_id="e-usage",
            phase_id=PHASE,
            workspace_id="w-usage",
        )
    ]


@pytest.mark.asyncio
async def test_finalize_records_usage_measured_at_teardown() -> None:
    writer = _Writer()
    await _runtime(writer).finalize(
        PHASE,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=0,
        duration_seconds=0.0,
    )
    _assert_one_row(writer)


@pytest.mark.asyncio
async def test_a_failed_attempt_records_its_usage() -> None:
    writer = _Writer()
    await _runtime(writer).abandon_phase("e-usage", PHASE, reason="attempt failed")
    _assert_one_row(writer)


@pytest.mark.asyncio
async def test_execution_failure_or_cancel_records_usage() -> None:
    writer = _Writer()
    await _runtime(writer).abandon_all("cancellation")
    _assert_one_row(writer)


@pytest.mark.asyncio
async def test_a_failed_write_does_not_fail_teardown() -> None:
    writer = _Writer(fail=RuntimeError("timescale down"))
    # Must not raise.
    await _runtime(writer).abandon_phase("e-usage", PHASE, reason="attempt failed")


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    workspace = _Workspace()
    workspace.teardown_usage = USAGE
    with pytest.raises(asyncio.CancelledError):
        await record_workspace_usage(
            _Writer(fail=asyncio.CancelledError()),
            cast("ManagedWorkspace", workspace),
            session_id=SESSION,
            phase_id=PHASE,
        )


@pytest.mark.asyncio
async def test_nothing_measured_writes_nothing() -> None:
    writer = _Writer()
    await record_workspace_usage(
        writer, cast("ManagedWorkspace", _Workspace()), session_id=SESSION, phase_id=PHASE
    )
    assert writer.usage_rows() == []


@pytest.mark.asyncio
async def test_an_unterminated_workspace_records_no_lifetime() -> None:
    """No termination time, no interval: a rate needs both ends (#1716)."""
    writer = _Writer()
    workspace = _Workspace(_Aggregate(terminated_at=None, lifetime_seconds=5.0))
    workspace.teardown_usage = USAGE
    await record_workspace_usage(
        writer, cast("ManagedWorkspace", workspace), session_id=SESSION, phase_id=PHASE
    )
    (row,) = writer.usage_rows()
    assert row.data["workspace_lifetime_seconds"] is None  # type: ignore[index]
