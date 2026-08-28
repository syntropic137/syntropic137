"""Fetching a delegate's usage from the session store (#895).

THE ROUND TRIP IS THE POINT. Two defects reached review in consecutive rounds
because nothing exercised retrieval end to end: a source_format literal that
matched no real record, and a document type the store does not produce. Both
times the code was self-consistent and disagreed with the store.

So these tests feed a RECORDED REAL store record straight through: its own
source_format string, its own raw body, in the shapes the store actually
returns them. The store serves raw as a list on the detail endpoint and as
JSON text from /raw, and both must price identically or a delegation's cost
depends on which endpoint the caller happened to use.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from syn_domain.contexts.agent_sessions.delegate_usage import (
    StoredSession,
    resolve_delegate_usage,
)
from syn_domain.contexts.agent_sessions.transcript_usage import (
    PricedUsage,
    UnpricedUsage,
)

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "delegation"


def _codex_raw() -> list[object]:
    return json.loads((_FIXTURES / "codex_rollout_usage.json").read_text())


def _claude_raw() -> str:
    return (_FIXTURES / "claude_transcript_usage.jsonl").read_text()


def _record(agent: str) -> dict[str, str]:
    recorded = json.loads((_FIXTURES / "store_session_records.json").read_text())
    return recorded["codex" if agent == "Codex" else "claude"]


class _FakeStore:
    """Returns what the real store returns, in the shape it returns it."""

    def __init__(self, sessions: dict[str, StoredSession]) -> None:
        self._sessions = sessions

    async def fetch_session(self, session_id: str) -> StoredSession | None:
        return self._sessions.get(session_id)


def _stored(agent: str, raw: object) -> StoredSession:
    record = _record(agent)
    return StoredSession(
        session_id=record["session_id"],
        source_format=record["source_format"],
        raw=raw,  # type: ignore[arg-type]
        model=None,
    )


@pytest.mark.unit
class TestTheRoundTrip:
    @pytest.mark.asyncio
    async def test_codex_prices_from_the_stores_own_identifiers(self) -> None:
        """The real source_format string, not the one the code assumes."""
        session = _stored("Codex", _codex_raw())
        store = _FakeStore({session.session_id: session})

        result = await resolve_delegate_usage(store, session.session_id)

        assert isinstance(result, PricedUsage)
        assert result.uncached_input_tokens == 49250 - 45056

    @pytest.mark.asyncio
    async def test_codex_prices_the_same_from_raw_text(self) -> None:
        """The detail endpoint serves raw as a list; /raw serves JSON text.

        If these disagreed, a delegation's cost would depend on which endpoint
        the caller reached for.
        """
        as_list = _stored("Codex", _codex_raw())
        as_text = _stored("Codex", json.dumps(_codex_raw()))

        from_list = await resolve_delegate_usage(
            _FakeStore({as_list.session_id: as_list}), as_list.session_id
        )
        from_text = await resolve_delegate_usage(
            _FakeStore({as_text.session_id: as_text}), as_text.session_id
        )

        assert from_list == from_text
        assert isinstance(from_list, PricedUsage)

    @pytest.mark.asyncio
    async def test_claude_prices_from_the_stores_own_identifiers(self) -> None:
        session = _stored("ClaudeCode", _claude_raw())
        store = _FakeStore({session.session_id: session})

        result = await resolve_delegate_usage(store, session.session_id)

        assert isinstance(result, PricedUsage)
        assert result.uncached_input_tokens == 7


@pytest.mark.unit
class TestAMissingSessionIsNotAFreeOne:
    @pytest.mark.asyncio
    async def test_an_absent_session_is_unpriced(self) -> None:
        """A delegate whose transcript never arrived is UNKNOWN, not free.

        Returning zero here would report a delegation that may have cost real
        money as costing nothing, which is the failure this issue exists to
        remove.
        """
        result = await resolve_delegate_usage(_FakeStore({}), "never-uploaded")

        assert isinstance(result, UnpricedUsage)
        assert "never-uploaded" in result.reason

    @pytest.mark.asyncio
    async def test_a_store_that_raises_is_unpriced_not_fatal(self) -> None:
        """One unreachable session must not fail the import of the rest."""

        class _BrokenStore:
            async def fetch_session(self, session_id: str) -> StoredSession | None:
                msg = "connection reset"
                raise ConnectionError(msg)

        result = await resolve_delegate_usage(_BrokenStore(), "some-id")

        assert isinstance(result, UnpricedUsage)
        assert "connection reset" in result.reason
