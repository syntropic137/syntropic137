"""The adapter's three inverted behaviours, each asserted directly.

These are not style tests. Each inversion exists because the OPPOSITE - the
conventional adapter choice - silently breaks a retry classification or a
correctness guard one layer up, with nothing going red.
"""

from __future__ import annotations

import json

import httpx
import pytest

from syn_adapters.session_store.http_store import HttpSessionStore, SessionStoreResponseError
from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort

pytestmark = pytest.mark.unit

_RECORD = {
    "session_id": "01a0472d-0815-79b0-bda7-ea7c9cb51686",
    "source_format": "codex-rollout-jsonl",
    "raw": [{"type": "session_meta", "payload": {"id": "x"}}],
    "metadata": {"model": "gpt-5.6-sol"},
}


def _store(handler) -> HttpSessionStore:
    transport = httpx.MockTransport(handler)
    return HttpSessionStore("http://store.test", client=httpx.AsyncClient(transport=transport))


def test_satisfies_the_port_protocol() -> None:
    assert isinstance(_store(lambda _: httpx.Response(200, json=_RECORD)), SessionStorePort)


@pytest.mark.asyncio
async def test_returns_the_record_as_the_store_reported_it() -> None:
    s = await _store(lambda _: httpx.Response(200, json=_RECORD)).fetch_session(
        _RECORD["session_id"]
    )
    assert s is not None
    assert s.session_id == _RECORD["session_id"]
    assert s.source_format == "codex-rollout-jsonl"
    assert s.raw == _RECORD["raw"]
    assert s.model == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_none_only_for_a_genuine_404() -> None:
    s = await _store(lambda _: httpx.Response(404)).fetch_session("missing")
    assert s is None, "a 404 is the one absence the store can actually assert"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503, 429, 401])
async def test_transport_and_server_faults_RAISE_rather_than_returning_none(status: int) -> None:
    """The inversion that matters most.

    resolve_delegate_usage catches Exception -> TRANSIENT ("retry under a
    bound"). Returning None here would classify the same failure as MISSING,
    which is retired on different terms. A 5xx recorded as "no transcript"
    prices a delegate at nothing, permanently.
    """
    with pytest.raises(httpx.HTTPStatusError):
        await _store(lambda _: httpx.Response(status)).fetch_session("s-1")


@pytest.mark.asyncio
async def test_connection_error_raises() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("reset", request=request)

    with pytest.raises(httpx.ConnectError):
        await _store(boom).fetch_session("s-1")


@pytest.mark.asyncio
async def test_does_NOT_stamp_the_requested_id_onto_the_response() -> None:
    """The guard this would silently disable.

    The caller refuses a record whose session_id differs from the one asked
    for - that is what stops a stale or misrouted response handing back the
    LEADER's transcript under a delegate's attribution. If this adapter
    'helpfully' normalised the id, that check would compare a value against
    itself and pass forever.
    """
    other = dict(_RECORD, session_id="a-completely-different-session")
    s = await _store(lambda _: httpx.Response(200, json=other)).fetch_session("the-one-i-asked-for")
    assert s is not None
    assert s.session_id == "a-completely-different-session", (
        "the adapter must report the id the STORE returned, so the caller's "
        "mismatch guard has something real to compare"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record,missing",
    [
        ({"source_format": "x", "raw": "y"}, "session_id"),
        ({"session_id": "s", "raw": "y"}, "source_format"),
        ({"session_id": "s", "source_format": "x"}, "raw"),
    ],
)
async def test_refuses_a_record_missing_a_required_field(record: dict, missing: str) -> None:
    """Refused, not guessed. Inferring source_format is what produced a literal
    matching no real record and left every codex transcript unpriced."""
    with pytest.raises(SessionStoreResponseError):
        await _store(lambda _: httpx.Response(200, json=record)).fetch_session("s")


@pytest.mark.asyncio
async def test_raw_passes_through_unnormalised_for_both_shapes() -> None:
    """The detail endpoint serves codex raw as a LIST, /raw serves it as TEXT.
    Both are valid and _as_rollout accepts either, so normalising here would
    discard a shape the layer below handles."""
    as_text = dict(_RECORD, raw=json.dumps(_RECORD["raw"]))
    s = await _store(lambda _: httpx.Response(200, json=as_text)).fetch_session(
        _RECORD["session_id"]
    )
    assert isinstance(s.raw, str)

    s2 = await _store(lambda _: httpx.Response(200, json=_RECORD)).fetch_session(
        _RECORD["session_id"]
    )
    assert isinstance(s2.raw, list)


def test_refuses_to_construct_without_a_url() -> None:
    """ADR-060 fail-fast: an unconfigured store is a wiring error, not a
    silent degradation into pricing nothing."""
    with pytest.raises(ValueError):
        HttpSessionStore("")


class TestMetadataModelIsNotThePricingAuthority:
    """metadata.model is the MODEL for claude and the PROVIDER for codex.

    Captured from live records on 2026-08-28 (fixtures/live_store_metadata.json).
    Pricing from this field returns UNPRICED for every codex delegate, because
    nothing has a rate for "openai".

    The reason this needs a test rather than a comment is the DIRECTION of the
    error: metadata is correct for claude and wrong for codex, so a
    "metadata usually works" shortcut passes a claude test and ships broken.
    The wrong thing is only wrong in the case nobody wrote a test for.
    """

    @staticmethod
    def _records() -> dict:
        import pathlib

        p = pathlib.Path(__file__).parent / "fixtures" / "live_store_metadata.json"
        return json.loads(p.read_text())["records"]

    def test_codex_metadata_reports_a_provider_not_a_model(self) -> None:
        codex = self._records()["codex"]
        assert codex["metadata"]["model"] == "openai", (
            "if the store starts reporting a real model here, this guard should "
            "be revisited rather than silently relied upon"
        )
        assert codex["agent"] == "Codex"

    def test_claude_metadata_reports_a_real_model_which_is_the_trap(self) -> None:
        claude = self._records()["claude"]
        assert claude["metadata"]["model"] == "claude-sonnet-4-6", (
            "metadata being RIGHT here is what makes it dangerous: a claude-only "
            "test of a metadata shortcut passes"
        )

    @pytest.mark.asyncio
    async def test_adapter_surfaces_metadata_model_without_pricing_from_it(self) -> None:
        """The adapter reports the field faithfully; it must not substitute the
        transcript's model, because the caller decides which is authoritative."""
        codex = self._records()["codex"]
        record = {
            "session_id": codex["session_id"],
            "source_format": codex["source_format"],
            "raw": [{"type": "session_meta", "payload": {}}],
            "metadata": {"model": codex["metadata"]["model"]},
        }
        s = await _store(lambda _: httpx.Response(200, json=record)).fetch_session(
            codex["session_id"]
        )
        assert s is not None
        assert s.model == "openai", "reported as-is; the transcript is what prices"
