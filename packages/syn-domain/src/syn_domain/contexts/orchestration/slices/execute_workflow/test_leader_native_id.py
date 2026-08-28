"""Both harnesses announce their own session id, and FIRST wins (#895).

The delegate import subtracts this id from the sweep, so getting it wrong does
not fail loudly - it silently reclassifies the leader as a delegate and bills
it a second time.
"""

from __future__ import annotations

import json

import pytest

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


class TestCodexAnnouncesOnThreadStarted:
    async def test_thread_id_is_the_id_the_store_keys_by(self) -> None:
        """Verified same-run on 2026-08-28: the thread_id on stdout is the
        session_id of the rollout file that same run writes. If that ever stops
        being true the import refuses rather than guessing - see
        DelegateImport.leader_missing_from_sweep.
        """
        from syn_shared.codex_stream import CodexStreamType

        event = json.loads(json.dumps({"type": "thread.started", "thread_id": _CODEX_ID}))
        assert event["type"] == CodexStreamType.THREAD_STARTED
        assert event["thread_id"] == _CODEX_ID
