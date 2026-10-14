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
from agentic_isolation import TeardownReport
from agentic_isolation.contract import (
    MISSING,
    FinalizationOutcome,
    OperationError,
    WorkspaceRef,
)
from agentic_isolation.providers.teardown_report import TeardownUsage

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


_USAGE = TeardownUsage(
    cpu_usage_seconds=4.25,
    nr_throttled=0,
    memory_peak_bytes=123_456_789,
    oom_kills=0,
    oom_killed=False,
    disk_bytes_at_teardown=2048,
    delete_failures=("/ws/a", "/ws/b"),
    net_rx_bytes=10,
    net_tx_bytes=20,
)
_COMPLETED = FinalizationOutcome(schema=MISSING, state="completed")


class _Provider:
    """agentic-workspace's staged teardown, answering with a fixed report."""

    def __init__(self, report: TeardownReport) -> None:
        self._report = report
        self.targets: list[object] = []

    async def teardown(self, *, target: object) -> TeardownReport:
        self.targets.append(target)
        return self._report


def _adapter(report: TeardownReport) -> tuple[AgenticIsolationAdapter, _Provider]:
    adapter = object.__new__(AgenticIsolationAdapter)
    workspace = object()
    adapter._workspaces = {"iso-1": workspace}  # type: ignore[assignment]
    provider = _Provider(report)
    adapter._provider = provider  # type: ignore[assignment]
    return adapter, provider


_HANDLE = IsolationHandle(isolation_id="iso-1", isolation_type="docker")


@pytest.mark.asyncio
async def test_agentic_adapter_maps_the_provider_report() -> None:
    adapter, provider = _adapter(TeardownReport(finalization=_COMPLETED, usage=_USAGE))
    usage = await adapter.destroy(_HANDLE)
    assert len(provider.targets) == 1, "torn down through teardown(target=...)"
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
async def test_a_retained_teardown_is_logged_and_still_reports_usage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retained = FinalizationOutcome(
        schema=MISSING,
        state="retained",
        stage="before_delete",
        error=OperationError(
            schema=MISSING, kind="provider_unavailable", message="archive upload failed"
        ),
        retained=WorkspaceRef(schema=MISSING, provider="docker", resource_id="iso-1"),
    )
    adapter, _ = _adapter(TeardownReport(finalization=retained, usage=_USAGE))

    with caplog.at_level(logging.ERROR):
        usage = await adapter.destroy(_HANDLE)

    assert usage is not None and usage.disk_bytes_at_teardown == 2048
    assert "retained" in caplog.text
    assert "archive upload failed" in caplog.text


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
