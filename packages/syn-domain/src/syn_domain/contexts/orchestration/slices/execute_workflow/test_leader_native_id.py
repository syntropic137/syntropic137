"""Both harnesses announce their own session id, and FIRST wins (#895).

The delegate import subtracts this id from the sweep, so getting it wrong does
not fail loudly - it silently reclassifies the leader as a delegate and bills
it a second time.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _make_processor as _make_codex_processor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _NoopWorkspace,
    _RecordingCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    _lines_to_stream,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        StreamResult,
    )

pytestmark = pytest.mark.unit

_CLAUDE_ID = "d5b0f1d5-ba23-4125-ba46-23ae1ed14bec"
_CODEX_ID = "01a04903-c2f9-7de3-a83f-7791cbc1a002"


def _claude_line(session_id: str, line_type: str = "system") -> str:
    return json.dumps({"type": line_type, "session_id": session_id})


class TestClaudeAnnouncesOnEveryLine:
    """Drives the REAL _process_cli_event. An earlier version of this test
    reimplemented the capture inline, which made it unable to fail when the
    processor changed - it tested a copy of the logic, not the logic.
    """

    @staticmethod
    def _processor():
        from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
            EventStreamProcessor,
        )

        proc = object.__new__(EventStreamProcessor)
        proc._leader_native_session_id = None
        # The same first-wins capture shape, for the announced model (#1284).
        proc._announced_model = None
        return proc

    async def test_the_first_announced_id_is_kept(self) -> None:
        proc = self._processor()

        await proc._process_cli_event(_claude_line(_CLAUDE_ID))
        await proc._process_cli_event(_claude_line("a-later-different-id", "system"))

        assert proc._leader_native_session_id == _CLAUDE_ID

    async def test_a_blank_id_is_not_taken(self) -> None:
        """A blank would derive one shared platform id for every delegate."""
        proc = self._processor()

        await proc._process_cli_event(_claude_line("   "))

        assert proc._leader_native_session_id is None

    async def test_a_line_announcing_nothing_leaves_it_unset(self) -> None:
        proc = self._processor()

        await proc._process_cli_event(json.dumps({"type": "system"}))

        assert proc._leader_native_session_id is None


def _codex_line(thread_id: str | None = None, line_type: str = "thread.started") -> str:
    event: dict[str, str] = {"type": line_type}
    if thread_id is not None:
        event["thread_id"] = thread_id
    return json.dumps(event)


async def _codex_result(*lines: str) -> StreamResult:
    """Run a codex stream end to end and hand back what it reported.

    Asserts on `StreamResult`, not on the processor's private attribute, because
    the attribute is not what anything downstream reads: `delegate_import` gets
    this id off the result, so a capture that works but is dropped on the way
    out is the failure worth catching.
    """
    processor, _tokens = _make_codex_processor(_RecordingCollector())
    return await processor.process_stream(_lines_to_stream(*lines), _NoopWorkspace())


class TestCodexAnnouncesOnThreadStarted:
    """Drives the REAL process_stream, for the reason stated one class up.

    This class used to load JSON it had just dumped and assert the key was
    still there, so it passed whatever the processor did - including doing
    nothing at all. The codex half of the capture had no test that could fail.
    """

    async def test_thread_id_is_the_id_the_store_keys_by(self) -> None:
        """Verified same-run on 2026-08-28: the thread_id on stdout is the
        session_id of the rollout file that same run writes. If that ever stops
        being true the import refuses rather than guessing - see
        DelegateImport.leader_missing_from_sweep.
        """
        result = await _codex_result(_codex_line(_CODEX_ID))

        assert result.leader_native_session_id == _CODEX_ID

    async def test_the_first_announced_id_is_kept(self) -> None:
        """A rebind mid-run would bill the leader a second time as a delegate."""
        result = await _codex_result(
            _codex_line(_CODEX_ID),
            _codex_line("01a04903-c2f9-7de3-a83f-000000000002"),
        )

        assert result.leader_native_session_id == _CODEX_ID

    async def test_a_blank_id_is_not_taken(self) -> None:
        """A blank would derive one shared platform id for every delegate."""
        result = await _codex_result(_codex_line("   "))

        assert result.leader_native_session_id is None

    async def test_an_id_announced_on_another_event_is_not_taken(self) -> None:
        """Only `thread.started` announces the leader. Reading a `thread_id`
        off any other event would take whatever a nested item happened to
        carry, which is not the same identity.
        """
        result = await _codex_result(_codex_line(_CODEX_ID, line_type="turn.started"))

        assert result.leader_native_session_id is None

    async def test_a_line_announcing_nothing_leaves_it_unset(self) -> None:
        result = await _codex_result(_codex_line())

        assert result.leader_native_session_id is None
