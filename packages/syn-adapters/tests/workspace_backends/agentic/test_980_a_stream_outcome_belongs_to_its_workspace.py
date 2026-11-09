"""#980: a stream's outcome belongs to its workspace, never to the shared adapter.

One `AgenticEventStreamAdapter` serves every workspace of its service, so two
phases stream through the same object at once. Each test here drives the REAL
adapter, and the real `ManagedWorkspace` reading it, with two workspaces whose
streams overlap: one ends, the other ends differently, and only then is the
first one's outcome read. That is the Codex window, where the handler reads the
exit code only after `record_session_summary()` has awaited.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from agentic_isolation.contract import MISSING, OperationRef, OperationSpec, OperationStatus
from test_stream_on_operations import RecordingOperations, _credentials, _Host

from syn_adapters.workspace_backends.agentic.stream_adapter import AgenticEventStreamAdapter
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from agentic_isolation.providers.base import Workspace

pytestmark = pytest.mark.unit

_A = IsolationHandle(isolation_id="ws-a", isolation_type="docker")
_B = IsolationHandle(isolation_id="ws-b", isolation_type="docker")


class _PerWorkspaceOperations(RecordingOperations):
    """Ends each workspace's operation the way that workspace was scripted to.

    ``ends`` maps an isolation id to ``(state, exit_code, signal)``; the spec's
    ``execution_id`` is the isolation id, so the status is chosen per stream.
    """

    def __init__(
        self,
        pages: Sequence[bytes | int | None],
        ends: dict[str, tuple[str, int | None, str | None]],
    ) -> None:
        super().__init__(_credentials(), pages)
        self._ends = ends
        self._workspace_of: dict[str, str] = {}

    async def start(self, workspace: Workspace, spec: OperationSpec) -> OperationRef:
        self._workspace_of[spec.operation_key] = spec.execution_id
        return await super().start(workspace, spec)

    async def status(self, ref: OperationRef) -> OperationStatus:
        isolation_id = self._workspace_of[ref.operation_key]
        state, exit_code, signal = self._ends[isolation_id]
        return OperationStatus(
            schema=MISSING,
            ref=ref,
            state=state,  # type: ignore[arg-type]
            exit_code=exit_code,
            signal=signal,
            execution_id=isolation_id,
            metadata={},
        )


def _adapter(
    ends: dict[str, tuple[str, int | None, str | None]],
    pages: Sequence[bytes | int | None] = (b"first\n", b"last\n"),
) -> AgenticEventStreamAdapter:
    host = _Host(_PerWorkspaceOperations(pages, ends), _credentials())  # type: ignore[arg-type]
    # The diagnostic must not read this host's kernel log in a unit test.
    host.shares_host_kernel = False
    return AgenticEventStreamAdapter(host)  # type: ignore[arg-type]


def _workspace(adapter: AgenticEventStreamAdapter, handle: IsolationHandle) -> ManagedWorkspace:
    service = MagicMock()
    service._event_stream = adapter
    return ManagedWorkspace(handle.isolation_id, "exec-980", MagicMock(), handle, None, service)


async def _drain(stream: AsyncIterator[str]) -> None:
    async for _ in stream:
        pass


async def test_a_success_does_not_inherit_a_concurrent_timeout() -> None:
    adapter = _adapter({"ws-a": ("succeeded", 0, None), "ws-b": ("timed_out", 0, None)})
    a, b = _workspace(adapter, _A), _workspace(adapter, _B)

    stream_a, stream_b = a.stream(["claude"]), b.stream(["claude"], timeout_seconds=1)
    assert await anext(stream_a) == "first"  # A is running when B starts
    await _drain(stream_b)  # B settles first
    await _drain(stream_a)  # A ends 0 ...
    first_read_of_a = a.last_stream_exit_code
    await _drain(b.stream(["claude"], timeout_seconds=1))  # ... B times out again before A is read

    assert first_read_of_a == 0
    assert a.last_stream_exit_code == 0, "A succeeded; 124 is B's timeout"
    assert b.last_stream_exit_code == 124


async def test_a_clean_exit_does_not_erase_a_concurrent_signal_death() -> None:
    adapter = _adapter({"ws-a": ("failed", None, "SIGSEGV"), "ws-b": ("succeeded", 0, None)})
    a, b = _workspace(adapter, _A), _workspace(adapter, _B)

    await _drain(a.stream(["claude"]))
    await _drain(b.stream(["claude"]))

    death = adapter.signal_death_of(_A)
    assert death is not None, "B's clean exit must not erase how A died"
    assert death.signal_number == 11
    assert a.last_stream_exit_code == 139
    assert adapter.signal_death_of(_B) is None
    assert b.last_stream_exit_code == 0


async def test_one_workspaces_lost_output_is_not_reset_by_another_stream() -> None:
    adapter = _adapter(
        {"ws-a": ("succeeded", 0, None), "ws-b": ("succeeded", 0, None)},
        pages=(b"first\n", 42, b"last\n"),
    )
    operations: _PerWorkspaceOperations = adapter._host.operations  # type: ignore[attr-defined]

    await _drain(adapter.stream(_A, ["claude"]))  # A loses 42 bytes ...
    operations._pages = [b"clean\n"]
    await _drain(adapter.stream(_B, ["claude"]))  # ... B loses nothing

    assert adapter.lost_bytes_of(_A) == 42
    assert adapter.lost_bytes_of(_B) == 0


async def test_a_single_workspace_reads_its_own_code_as_before() -> None:
    adapter = _adapter({"ws-a": ("failed", 3, None)})
    a = _workspace(adapter, _A)

    assert a.last_stream_exit_code is None, "no stream has completed yet"
    await _drain(a.stream(["claude"]))

    assert a.last_stream_exit_code == 3
    assert adapter.exit_code_of(_B) is None, "a workspace that never streamed has no code"
