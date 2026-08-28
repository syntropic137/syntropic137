"""Store adapter and import, together, over a real HTTP surface (#895).

Both halves were unit-tested against each other's doubles, which is exactly the
shape of test that passes while the seam is broken. This drives the real
``HttpSessionStore`` against real JSON: the record shapes come from a live
APS-V1-0004 store and the transcripts from real delegated runs, so a change to
either end fails here rather than in a live validation run.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from syn_adapters.session_store.http_store import HttpSessionStore
from syn_domain.contexts.agent_sessions.delegate_import import import_phase_delegates

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).parent / "fixtures"
_DOMAIN_FIXTURES = Path(__file__).parents[2] / "syn-domain" / "tests" / "fixtures" / "delegation"

LEADER = "01a0472d-0815-79b0-bda7-ea7c9cb51686"
DELEGATE = "01a04903-c2f9-7de3-a83f-7791cbc1a002"


def _live_records() -> dict[str, dict[str, object]]:
    return json.loads((_FIXTURES / "live_store_metadata.json").read_text())["records"]


def _claude_transcript() -> str:
    return (_DOMAIN_FIXTURES / "claude_transcript_usage.jsonl").read_text()


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str | None]] = []

    async def record_delegate_usage(
        self,
        *,
        session_id: str,
        usage: object,
        unpriced_reason: str | None,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
    ) -> None:
        self.calls.append((session_id, usage, unpriced_reason))


def _serving(bodies: dict[str, dict[str, object]]) -> HttpSessionStore:
    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.url.path.rsplit("/", 1)[-1]
        if sid not in bodies:
            return httpx.Response(404)
        return httpx.Response(200, json=bodies[sid])

    return HttpSessionStore(
        base_url="http://store.invalid",
        auth_token="t",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_a_delegate_is_priced_from_a_record_the_store_really_serves() -> None:
    """The end-to-end path a live run exercises, minus the live run."""
    claude = dict(_live_records()["claude"])
    claude["session_id"] = DELEGATE
    claude["raw"] = _claude_transcript()

    recorder = _Recorder()
    result = await import_phase_delegates(
        _serving({DELEGATE: claude}),
        recorder,
        leader_native_session_id=LEADER,
        captured_session_ids=[LEADER, DELEGATE],
        execution_id="exec-http",
        phase_id="phase-1",
        attempts_remaining=0,
    )

    assert len(recorder.calls) == 1, "exactly one delegate should have been recorded"
    _, usage, reason = recorder.calls[0]
    assert reason is None, f"delegate should have priced, got: {reason}"
    assert usage is not None
    assert usage.output_tokens > 0, "a real transcript must yield real output tokens"
    assert result.imported[0].priced


async def test_the_leader_is_never_fetched_even_when_the_store_has_it() -> None:
    """Not fetching is a stronger guarantee than fetching and discarding:
    there is then no path on which the leader's tokens reach a total."""
    claude = dict(_live_records()["claude"])
    claude["session_id"] = DELEGATE
    claude["raw"] = _claude_transcript()
    leader = dict(_live_records()["codex"])
    leader["session_id"] = LEADER
    leader["raw"] = _claude_transcript()

    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.url.path.rsplit("/", 1)[-1]
        asked.append(sid)
        body = {LEADER: leader, DELEGATE: claude}.get(sid)
        return httpx.Response(200, json=body) if body else httpx.Response(404)

    store = HttpSessionStore(
        base_url="http://store.invalid",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await import_phase_delegates(
        store,
        _Recorder(),
        leader_native_session_id=LEADER,
        captured_session_ids=[LEADER, DELEGATE],
        execution_id="exec-http",
        phase_id="phase-1",
        attempts_remaining=0,
    )

    assert LEADER not in asked
    assert asked == [DELEGATE]


async def test_a_store_that_does_not_have_it_yet_becomes_a_named_gap() -> None:
    """404 with no budget left: recorded as unpriced with a reason, never
    dropped. A dropped delegate is indistinguishable from one that never ran."""
    recorder = _Recorder()
    await import_phase_delegates(
        _serving({}),
        recorder,
        leader_native_session_id=LEADER,
        captured_session_ids=[LEADER, DELEGATE],
        execution_id="exec-http",
        phase_id="phase-1",
        attempts_remaining=0,
    )

    assert len(recorder.calls) == 1
    _, usage, reason = recorder.calls[0]
    assert usage is None
    assert reason
    # A genuine absence must NOT be reported as a store failure. The two need
    # opposite handling - one is the store answering honestly, the other is the
    # store not answering - and an adapter that raises on 404 makes every
    # missing delegate look like an outage that will clear on retry.
    assert "store lookup failed" not in reason, (
        f"a 404 was reported as a transport fault: {reason!r}"
    )


async def test_a_server_fault_is_reported_differently_from_an_absence() -> None:
    """The other side of the same invariant, so neither can collapse into the
    other without a test noticing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    store = HttpSessionStore(
        base_url="http://store.invalid",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    recorder = _Recorder()
    await import_phase_delegates(
        store,
        recorder,
        leader_native_session_id=LEADER,
        captured_session_ids=[LEADER, DELEGATE],
        execution_id="exec-http",
        phase_id="phase-1",
        attempts_remaining=0,
    )

    _, usage, reason = recorder.calls[0]
    assert usage is None
    assert reason and "store lookup failed" in reason
