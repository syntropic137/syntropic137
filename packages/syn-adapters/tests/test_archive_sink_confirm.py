"""Revision confirmation outcomes and the confirmed-expiry gate (#2107 S5).

The SeshMagic adapter runs against ``httpx.MockTransport``, never a live store.
Every status the draft contract defines maps to exactly one outcome, and no
outcome is folded into "absent" or "confirmed" (APSS PR #154, base 5.3.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from syn_adapters.session_inventory.expiry_gate import ConfirmedExpiryGate, ExpiryHold
from syn_adapters.session_inventory.replication_runtime import create_expiry_gate
from syn_adapters.session_store.seshmagic_archive_sink import (
    CAPABILITIES_PATH,
    CONFIRM_PATH,
    STORED_HASH_HEADER,
    SeshMagicArchiveSink,
)
from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import (
    ArchiveUnavailable,
    ConfirmNotAdvertised,
    ConfirmUnauthorized,
    ConfirmUnexpectedResponse,
    RevisionAbsent,
    RevisionConfirmation,
    RevisionConfirmed,
    RevisionIntegrityFailure,
    UploadedRevision,
)
from syn_shared.settings.session_inventory import SessionInventorySettings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_BASE = "https://seshmagic.test"
_STORED = "sha256:" + "b" * 64
_REVISION = UploadedRevision(
    source_instance_id="install-1",
    harness="claude",
    native_session_id="native-1",
    content_hash="sha256:" + "a" * 64,
)
_ADVERTISED = {"revision_confirm": True, "confirm_verifies_body": True, "request_encodings": []}


def _sink(
    confirm: httpx.Response | Exception,
    capabilities: httpx.Response | None = None,
    seen: list[httpx.Request] | None = None,
) -> SeshMagicArchiveSink:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == CAPABILITIES_PATH:
            return capabilities or httpx.Response(200, json=_ADVERTISED)
        if isinstance(confirm, Exception):
            raise confirm
        return confirm

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SeshMagicArchiveSink(_BASE, SecretStr("read-token"), client=client)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(200, headers={STORED_HASH_HEADER: _STORED}),
            RevisionConfirmed(stored_content_hash=_STORED, body_verified=True),
        ),
        (httpx.Response(404), RevisionAbsent()),
        (httpx.Response(401), ConfirmUnauthorized(status=401)),
        (httpx.Response(403), ConfirmUnauthorized(status=403)),
        (httpx.Response(409), RevisionIntegrityFailure()),
        (httpx.Response(503), ArchiveUnavailable()),
        # Outside the contract: never absent, never confirmed.
        (httpx.Response(200), ConfirmUnexpectedResponse(status=200)),
        (
            httpx.Response(200, headers={STORED_HASH_HEADER: "sha256:short"}),
            ConfirmUnexpectedResponse(status=200),
        ),
        (httpx.Response(500), ConfirmUnexpectedResponse(status=500)),
        (httpx.Response(400), ConfirmUnexpectedResponse(status=400)),
        (
            httpx.Response(302, headers={"Location": "https://elsewhere.test/"}),
            ConfirmUnexpectedResponse(status=302),
        ),
    ],
)
async def test_each_store_answer_maps_to_exactly_one_outcome(
    response: httpx.Response, expected: RevisionConfirmation
) -> None:
    assert await _sink(response).confirm(_REVISION) == expected


async def test_transport_failure_is_unavailable_not_absent() -> None:
    sink = _sink(httpx.ConnectError("refused"))
    assert await sink.confirm(_REVISION) == ArchiveUnavailable()


async def test_confirms_the_uploaded_qualified_revision_with_a_read_token() -> None:
    seen: list[httpx.Request] = []
    await _sink(httpx.Response(200, headers={STORED_HASH_HEADER: _STORED}), seen=seen).confirm(
        _REVISION
    )
    head = seen[-1]
    assert head.method == "HEAD"
    assert head.url.path == CONFIRM_PATH
    assert dict(head.url.params) == {
        "source_instance_id": "install-1",
        "harness": "claude",
        "native_session_id": "native-1",
        "content_hash": _REVISION.content_hash,
    }
    assert head.headers["Authorization"] == "Bearer read-token"


async def test_body_verified_reflects_the_advertised_capability() -> None:
    capabilities = httpx.Response(
        200, json={"revision_confirm": True, "confirm_verifies_body": False}
    )
    outcome = await _sink(
        httpx.Response(200, headers={STORED_HASH_HEADER: _STORED}), capabilities
    ).confirm(_REVISION)
    assert outcome == RevisionConfirmed(stored_content_hash=_STORED, body_verified=False)


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        (httpx.Response(404), ConfirmNotAdvertised()),
        (httpx.Response(200, json={"request_encodings": ["gzip"]}), ConfirmNotAdvertised()),
        (httpx.Response(200, json={"revision_confirm": False}), ConfirmNotAdvertised()),
        (httpx.Response(200, json={"revision_confirm": True}), ConfirmUnexpectedResponse(200)),
        (httpx.Response(200, content=b"not json"), ConfirmUnexpectedResponse(200)),
        (httpx.Response(503), ArchiveUnavailable()),
        (httpx.Response(401), ConfirmUnauthorized(status=401)),
    ],
)
async def test_capability_discovery_gates_the_confirm_request(
    capabilities: httpx.Response, expected: RevisionConfirmation
) -> None:
    seen: list[httpx.Request] = []
    # Were the HEAD sent, it would confirm: the capability answer must decide.
    sink = _sink(httpx.Response(200, headers={STORED_HASH_HEADER: _STORED}), capabilities, seen)
    assert await sink.confirm(_REVISION) == expected
    assert [request.method for request in seen] == ["GET"]


class _ScriptedSink:
    """Test double: answers per content hash and records what it was asked."""

    def __init__(self, answers: dict[str, RevisionConfirmation]) -> None:
        self.answers = answers
        self.asked: list[UploadedRevision] = []

    async def confirm(self, revision: UploadedRevision) -> RevisionConfirmation:
        self.asked.append(revision)
        return self.answers[revision.content_hash]


def _revision(n: int) -> UploadedRevision:
    return _REVISION.model_copy(update={"content_hash": f"sha256:{n:064x}"})


_CONFIRMED = RevisionConfirmed(stored_content_hash=_STORED, body_verified=True)


async def test_gate_permits_only_when_every_revision_is_confirmed_and_backup_attested() -> None:
    sink = _ScriptedSink(
        {_revision(1).content_hash: _CONFIRMED, _revision(2).content_hash: _CONFIRMED}
    )
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=True)
    decision = await gate.decide([_revision(1), _revision(2)], all_uploaded=True)
    assert decision.permitted
    assert sink.asked == [_revision(1), _revision(2)]
    assert gate.permitted == 1


@pytest.mark.parametrize(
    ("second", "hold"),
    [
        (RevisionAbsent(), ExpiryHold.ABSENT),
        (ConfirmUnauthorized(status=403), ExpiryHold.UNAUTHORIZED),
        (RevisionIntegrityFailure(), ExpiryHold.INTEGRITY_FAILURE),
        (ArchiveUnavailable(), ExpiryHold.UNAVAILABLE),
        (ConfirmNotAdvertised(), ExpiryHold.NOT_ADVERTISED),
        (ConfirmUnexpectedResponse(status=500), ExpiryHold.UNEXPECTED),
    ],
)
async def test_one_unconfirmed_revision_holds_the_whole_body(
    second: RevisionConfirmation, hold: ExpiryHold
) -> None:
    sink = _ScriptedSink({_revision(1).content_hash: _CONFIRMED, _revision(2).content_hash: second})
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=True)
    decision = await gate.decide([_revision(1), _revision(2)], all_uploaded=True)
    assert decision.hold is hold
    assert not decision.permitted
    assert gate.holds[hold] == 1


async def test_without_backup_attestation_nothing_is_permitted_or_asked() -> None:
    sink = _ScriptedSink({_revision(1).content_hash: _CONFIRMED})
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=False)
    decision = await gate.decide([_revision(1)], all_uploaded=True)
    assert decision.hold is ExpiryHold.NO_BACKUP_ATTESTATION
    assert sink.asked == []


@pytest.mark.parametrize("revisions", [[], [_revision(1)]])
async def test_a_body_with_any_capture_not_uploaded_is_held(
    revisions: list[UploadedRevision],
) -> None:
    sink = _ScriptedSink({_revision(1).content_hash: _CONFIRMED})
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=True)
    decision = await gate.decide(revisions, all_uploaded=False)
    assert decision.hold is ExpiryHold.NOT_UPLOADED
    empty = await gate.decide([], all_uploaded=True)
    assert empty.hold is ExpiryHold.NOT_UPLOADED


def _settings(
    tmp_path: Path,
    *,
    confirm: bool = False,
    read_token: str | None = None,
    capture: bool = True,
) -> SessionInventorySettings:
    return SessionInventorySettings(
        _env_file=None,
        archive_dir=tmp_path,
        replication_enabled=True,
        replication_store_url=_BASE,
        replication_write_token=SecretStr("inventory-token"),
        capture_replication_enabled=capture,
        capture_write_token=SecretStr("capture-token"),
        archive_confirm_enabled=confirm,
        archive_confirm_read_token=None if read_token is None else SecretStr(read_token),
    )


def test_gate_is_off_by_default(tmp_path: Path) -> None:
    settings = SessionInventorySettings(_env_file=None, archive_dir=tmp_path)
    assert not settings.archive_confirm_enabled
    assert not settings.archive_offsite_backup_attested
    assert create_expiry_gate(settings) is None
    assert create_expiry_gate(_settings(tmp_path, read_token="read-token")) is None


@pytest.mark.parametrize(
    ("read_token", "capture"),
    [(None, True), ("has space", True), ("", True), ("read-token", False)],
)
def test_enabling_the_gate_requires_capture_replication_and_a_read_token(
    tmp_path: Path, read_token: str | None, capture: bool
) -> None:
    with pytest.raises(ValidationError):
        _settings(tmp_path, confirm=True, read_token=read_token, capture=capture)


def test_enabled_gate_is_built_from_settings(tmp_path: Path) -> None:
    gate = create_expiry_gate(_settings(tmp_path, confirm=True, read_token="read-token"))
    assert isinstance(gate, ConfirmedExpiryGate)
