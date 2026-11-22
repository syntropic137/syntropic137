"""The domain prices a delegate without knowing any transcript format (#1424).

The reader here is a double that knows no harness. If resolving or importing
a delegate still needed the format, these could not pass: the store hands back
a label and a body no real parser accepts, and the only usage in sight is the
one the double returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from syn_domain.contexts.agent_sessions.delegate_import import import_phase_delegates
from syn_domain.contexts.agent_sessions.delegate_usage import (
    StoredSession,
    resolve_delegate_usage,
)
from syn_domain.contexts.agent_sessions.transcript_usage import (
    PricedUsage,
    StoredTranscript,
    UsageResult,
)

pytestmark = pytest.mark.unit

#: Values no real parse of anything here could produce.
_READ = PricedUsage(
    model="model-from-the-double",
    uncached_input_tokens=1301,
    cache_read_tokens=1307,
    cache_creation_tokens=1319,
    output_tokens=1321,
    message_count=3,
)


@dataclass
class _Reader:
    calls: list[tuple[str, StoredTranscript]] = field(default_factory=list)

    def read_usage(self, source_format: str, document: StoredTranscript) -> UsageResult:
        self.calls.append((source_format, document))
        return _READ


class _Store:
    async def fetch_session(self, session_id: str) -> StoredSession | None:
        return StoredSession(
            session_id=session_id, source_format="no-such-harness", raw="opaque body"
        )


async def test_resolve_returns_what_the_reader_read() -> None:
    reader = _Reader()

    result = await resolve_delegate_usage(_Store(), "delegate", reader=reader)

    assert result == _READ
    # The store's own label and body reach the reader untouched: the domain
    # neither interprets nor rewrites them.
    assert reader.calls == [("no-such-harness", "opaque body")]


@dataclass
class _Recorder:
    recorded: list[PricedUsage | None] = field(default_factory=list)

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
        self.recorded.append(usage)


async def test_import_prices_a_delegate_from_the_reader_alone() -> None:
    reader = _Reader()
    recorder = _Recorder()

    result = await import_phase_delegates(
        _Store(),
        recorder,
        reader=reader,
        leader_native_session_id="leader",
        captured_session_ids=("leader", "delegate"),
        execution_id="exec-1",
        phase_id="phase-1",
        attempts_remaining=0,
    )

    assert [d.priced for d in result.imported] == [True]
    # What was WRITTEN, not just what was read: the recorder is the consumer.
    assert recorder.recorded == [_READ]
    assert reader.calls == [("no-such-harness", "opaque body")]
