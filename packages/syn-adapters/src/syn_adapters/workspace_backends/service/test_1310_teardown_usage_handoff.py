"""What teardown measured reaches the caller's `ManagedWorkspace` (#1310).

The usage travels provider report -> `AgenticIsolationAdapter.destroy` ->
`_destroy_isolation` -> `cleanup_workspace` -> `create_workspace`'s `finally`
-> `ManagedWorkspace.teardown_usage`. Each hop returned None before this, so
each is a place the value can be dropped; these tests read it at the far end.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.teardown_usage import (
    USAGE_FIELDS,
    TeardownReportLike,
    usage_from_report,
)
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
    WorkspaceUsage,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

USAGE = WorkspaceUsage(memory_peak_bytes=987_654_321, oom_kills=2, delete_failures=("/x",))


@pytest.fixture(autouse=True)
def _test_env() -> Iterator[None]:
    with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
        yield


@pytest.mark.asyncio
async def test_usage_from_destroy_lands_on_the_managed_workspace() -> None:
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    real_destroy = service._isolation.destroy

    async def measuring_destroy(handle: IsolationHandle) -> WorkspaceUsage | None:
        await real_destroy(handle)
        return USAGE

    service._isolation.destroy = measuring_destroy  # type: ignore[method-assign]

    async with service.create_workspace(execution_id="e-1", phase_id="p-1") as workspace:
        assert workspace.teardown_usage is None  # not measured until teardown

    assert workspace.teardown_usage == USAGE


@pytest.mark.asyncio
async def test_a_failed_destroy_leaves_usage_unknown() -> None:
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

    async def failing_destroy(handle: IsolationHandle) -> WorkspaceUsage | None:
        raise RuntimeError("docker gone")

    service._isolation.destroy = failing_destroy  # type: ignore[method-assign]

    async with service.create_workspace(execution_id="e-1") as workspace:
        pass

    assert workspace.teardown_usage is None


@dataclass(frozen=True)
class _ProviderReport:
    """The shape agentic-workspace's `TeardownReport` is specified to have."""

    cpu_usage_seconds: float | None = 4.25
    cpu_throttled_seconds: float | None = None
    nr_throttled: int | None = 0
    memory_peak_bytes: int | None = 123_456_789
    oom_kills: int | None = 0
    disk_bytes_at_teardown: int | None = 2048
    delete_failures: tuple[str, ...] | None = ("/ws/a", "/ws/b")
    net_rx_bytes: int | None = 10
    net_tx_bytes: int | None = 20


class _Provider:
    def __init__(self, report: object) -> None:
        self._report = report

    async def destroy(self, _workspace: object) -> object:
        return self._report


def _adapter(report: object) -> AgenticIsolationAdapter:
    adapter = object.__new__(AgenticIsolationAdapter)
    adapter._workspaces = {"iso-1": object()}  # type: ignore[assignment]
    adapter._provider = _Provider(report)  # type: ignore[assignment]
    return adapter


@pytest.mark.asyncio
async def test_agentic_adapter_maps_the_provider_report() -> None:
    usage = await _adapter(_ProviderReport()).destroy(
        IsolationHandle(isolation_id="iso-1", isolation_type="docker")
    )
    assert usage == WorkspaceUsage(
        cpu_usage_seconds=4.25,
        cpu_throttled_seconds=None,
        nr_throttled=0,
        memory_peak_bytes=123_456_789,
        oom_kills=0,
        disk_bytes_at_teardown=2048,
        delete_failures=("/ws/a", "/ws/b"),
        net_rx_bytes=10,
        net_tx_bytes=20,
    )


@pytest.mark.asyncio
async def test_a_provider_that_reports_nothing_maps_to_none() -> None:
    # The pinned provider today: `destroy` returns None.
    usage = await _adapter(None).destroy(
        IsolationHandle(isolation_id="iso-1", isolation_type="docker")
    )
    assert usage is None


@dataclass(frozen=True)
class _RenamedFieldReport:
    """A provider that renamed `memory_peak_bytes`; every other field is valid."""

    cpu_usage_seconds: float | None = 4.25
    cpu_throttled_seconds: float | None = None
    nr_throttled: int | None = 0
    memory_peak: int | None = 123_456_789
    oom_kills: int | None = 1
    disk_bytes_at_teardown: int | None = 2048
    delete_failures: tuple[str, ...] | None = ()
    net_rx_bytes: int | None = 10
    net_tx_bytes: int | None = 20


def test_a_mismatched_report_is_logged_and_keeps_what_it_carries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        usage = usage_from_report(_RenamedFieldReport())

    assert usage == WorkspaceUsage(
        cpu_usage_seconds=4.25,
        nr_throttled=0,
        memory_peak_bytes=None,
        oom_kills=1,
        disk_bytes_at_teardown=2048,
        delete_failures=(),
        net_rx_bytes=10,
        net_tx_bytes=20,
    )
    mismatch = [r for r in caplog.records if "TeardownReportLike" in r.getMessage()]
    assert len(mismatch) == 1
    assert "_RenamedFieldReport" in mismatch[0].getMessage()
    assert "memory_peak_bytes" in mismatch[0].getMessage()


def test_a_report_with_no_known_field_is_logged_not_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        assert usage_from_report(object()) is None
    assert any("TeardownReportLike" in r.getMessage() for r in caplog.records)


def test_an_absent_report_is_not_a_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert usage_from_report(None) is None
    assert not caplog.records


def test_the_protocol_names_exactly_the_usage_fields() -> None:
    # The Protocol and `WorkspaceUsage` are two hand-written lists of the same
    # nine names; this pins them so neither can drift alone.
    members = {
        name for name, value in vars(TeardownReportLike).items() if isinstance(value, property)
    }
    assert members == set(USAGE_FIELDS)
