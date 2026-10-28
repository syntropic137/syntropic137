"""``run_bounded``: bounded memory, credentials withheld first, a typed end (ADR-078 D3).

Driven through a scripted double of ``SupportsOperations`` that serves the
pages it is told to, so a page boundary can split a line or a secret, and a
flood can arrive without one newline.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from agentic_isolation import WorkspaceConfig
from agentic_isolation.contract import (
    MISSING,
    ObservationGap,
    ObservationPage,
    OperationRef,
    OperationSpec,
    OperationStatus,
    WorkspaceRef,
)
from agentic_isolation.providers.base import Workspace

from syn_adapters.workspace_backends.agentic.bounded_output import BoundedOutput
from syn_adapters.workspace_backends.agentic.credential_scrubber import (
    REDACTED_MARKER,
    CredentialScrubber,
)
from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
from syn_adapters.workspace_backends.agentic.stream_adapter import AgenticEventStreamAdapter
from syn_domain.contexts.orchestration._shared.command_phase import CommandTerminal
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_shared.in_memory import InMemoryAdapter
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

#: Invented, never a real credential (fixture hygiene).
_SECRET = "ghs_SYNTHETIC0000NOT0A0CREDENTIAL0000"
_WS = WorkspaceRef(schema=MISSING, provider="recording", resource_id="ws-1")
_HANDLE = IsolationHandle(isolation_id="ws-1", isolation_type="docker")


class _Operations(InMemoryAdapter):
    """Serves scripted pages: bytes = data, int = a gap of that many lost bytes."""

    def __init__(
        self,
        pages: Sequence[bytes | int],
        *,
        state: str = "succeeded",
        exit_code: int | None = 0,
        fail_start: bool = False,
    ) -> None:
        super().__init__()
        self._pages = list(pages)
        self._state = state
        self._exit_code = exit_code
        self._fail_start = fail_start
        self.specs: list[OperationSpec] = []
        self.max_page = 0

    async def start(self, workspace: Workspace, spec: OperationSpec) -> OperationRef:
        if self._fail_start:
            raise RuntimeError("exec failed")
        self.specs.append(spec)
        return OperationRef(workspace=_WS, operation_id="op-1", operation_key=spec.operation_key)

    async def observe(
        self, ref: OperationRef, *, cursor: str | None, max_bytes: int, wait_seconds: float = 0
    ) -> ObservationPage:
        index = int(cursor or 0)
        item = self._pages[index] if self._pages else b""
        complete = index >= len(self._pages) - 1
        data = item if isinstance(item, bytes) else b""
        self.max_page = max(self.max_page, len(data))
        gap: Any = MISSING if isinstance(item, bytes) else ObservationGap(lost_bytes=item)
        return ObservationPage(
            schema=MISSING,
            ref=ref,
            state=self._state if complete else "running",  # type: ignore[arg-type]
            cursor=str(index),
            next_cursor=str(index + 1),
            data_b64=base64.b64encode(data).decode(),
            gap=gap,
            complete=complete,
        )

    async def status(self, ref: OperationRef) -> OperationStatus:
        return OperationStatus(
            schema=MISSING,
            ref=ref,
            state=self._state,  # type: ignore[arg-type]
            exit_code=self._exit_code,
            execution_id="ws-1",
            metadata={},
        )

    async def cancel(self, ref: OperationRef, *, grace_seconds: float) -> OperationStatus:
        self._state = "cancelled"
        self._exit_code = None
        return await self.status(ref)


class _Host:
    def __init__(self, operations: _Operations) -> None:
        self.operations = operations
        self.credentials = WorkspaceCredentials(SessionStoreSettings())
        self.shares_host_kernel = True

    def workspace(self, isolation_id: str) -> Workspace | None:
        return Workspace(
            id=isolation_id,
            provider="recording",
            path=Path("/nonexistent"),
            config=WorkspaceConfig(),
        )


async def _run(ops: _Operations, *, tail_bytes: int = 64, withheld: tuple[str, ...] = ()):
    adapter = AgenticEventStreamAdapter(_Host(ops))  # type: ignore[arg-type]
    return await adapter.run_bounded(
        _HANDLE,
        ["sh", "-c", "make"],
        timeout_seconds=30,
        tail_bytes=tail_bytes,
        withheld=lambda: withheld,
    )


async def test_a_clean_exit_is_exited_with_its_code_and_the_tail_of_output() -> None:
    result = await _run(_Operations([b"compiling\n", b"done\n"], exit_code=0))

    assert (result.terminal, result.exit_code) == (CommandTerminal.EXITED, 0)
    assert result.tail == "compiling\ndone\n"
    assert result.dropped_bytes == 0


async def test_an_explicit_exit_124_is_not_a_timeout() -> None:
    """``stream`` folds a timeout into 124; a gate must tell them apart."""
    exited = await _run(_Operations([b"x\n"], state="failed", exit_code=124))
    timed_out = await _run(_Operations([b"x\n"], state="timed_out", exit_code=None))

    assert (exited.terminal, exited.exit_code) == (CommandTerminal.EXITED, 124)
    assert (timed_out.terminal, timed_out.exit_code) == (CommandTerminal.TIMED_OUT, None)


async def test_a_lost_operation_and_a_start_failure_are_failed_to_start() -> None:
    lost = await _run(_Operations([b""], state="lost", exit_code=None))
    unstarted = await _run(_Operations([], fail_start=True))

    assert lost.terminal is CommandTerminal.FAILED_TO_START
    assert unstarted.terminal is CommandTerminal.FAILED_TO_START


async def test_a_flood_without_newlines_keeps_only_the_tail() -> None:
    """The ``LineDecoder`` hazard: an unterminated line held whole (codex pass 2, M2)."""
    page = b"#" * (1 << 20)
    ops = _Operations([page] * 8 + [b"END"])
    result = await _run(ops, tail_bytes=1024)

    assert len(result.tail.encode()) <= 1024
    assert result.tail.endswith("END")
    assert result.dropped_bytes == 8 * len(page) + 3 - len(result.tail.encode())


async def test_a_secret_split_across_pages_is_withheld_before_it_is_kept() -> None:
    half = len(_SECRET) // 2
    ops = _Operations([f"token={_SECRET[:half]}".encode(), f"{_SECRET[half:]} ok\n".encode()])
    result = await _run(ops, withheld=(_SECRET,))

    assert _SECRET not in result.tail
    assert _SECRET[:half] not in result.tail
    assert result.tail == f"token={REDACTED_MARKER} ok\n"


def test_a_secret_split_at_a_forced_cut_in_an_unterminated_line_is_withheld() -> None:
    """The cut path: a line longer than the hold limit, with the value across the cut."""
    scrubber = CredentialScrubber((_SECRET,))
    output = BoundedOutput(1 << 20, max_line_chars=100)
    head = "a" * 95 + _SECRET[:10]
    output.feed(head.encode(), scrubber)
    output.feed(_SECRET[10:].encode() + b"z", scrubber)
    output.finish(scrubber)

    assert _SECRET[:10] not in output.tail
    assert output.tail == "a" * 95 + REDACTED_MARKER + "z"


async def test_the_launch_announcement_is_not_part_of_the_tail() -> None:
    ops = _Operations([])
    adapter = AgenticEventStreamAdapter(_Host(ops))  # type: ignore[arg-type]

    async def observe_with_marker(
        ref: OperationRef, *, cursor: str | None, max_bytes: int, wait_seconds: float = 0
    ) -> ObservationPage:
        line = ops.specs[0].launch_marker.line
        return ObservationPage(
            schema=MISSING,
            ref=ref,
            state="succeeded",
            cursor="0",
            next_cursor="1",
            data_b64=base64.b64encode(f"{line}\nbuilt\n".encode()).decode(),
            gap=MISSING,
            complete=True,
        )

    ops.observe = observe_with_marker  # type: ignore[method-assign]
    result = await adapter.run_bounded(_HANDLE, ["sh", "-c", "make"], timeout_seconds=5)

    assert result.tail == "built\n"


async def test_a_gap_is_counted_as_dropped_output() -> None:
    result = await _run(_Operations([b"partial", 500, b"after\n"]))

    assert result.tail == "after\n"
    assert result.dropped_bytes == 500 + len(b"partial")


def test_the_tail_starts_at_a_whole_character() -> None:
    output = BoundedOutput(5)
    output.feed("ééé\n".encode(), CredentialScrubber())

    assert output.tail == "éé\n"
