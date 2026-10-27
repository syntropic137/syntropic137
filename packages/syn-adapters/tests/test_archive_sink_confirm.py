"""Revision confirmation through the exporter, the gate and its lane (#2107 S5).

The adapter runs a real subprocess: a stand-in exporter script that prints a
scripted ``--capture-confirm`` document (agentic-session-exporter PR #31), never
a live store. Every document maps to exactly one outcome, and nothing outside
the CLI contract is read as "absent" or "confirmed".
"""

from __future__ import annotations

import asyncio
import json
import stat
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError

from syn_adapters.session_inventory.archive_sink import ExporterArchiveSink
from syn_adapters.session_inventory.expiry_gate import ConfirmedExpiryGate, ExpiryHold
from syn_adapters.session_inventory.exporter_transport import ExporterConfirmConfig
from syn_adapters.session_inventory.replication_runtime import create_expiry_gate
from syn_adapters.session_inventory.retention_lane import RetentionLane
from syn_adapters.session_inventory.runtime import InventoryWork
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

_STORED = "sha256:" + "b" * 64
_REVISION = UploadedRevision(
    source_instance_id="install-1",
    harness="claude",
    native_session_id="native-1",
    content_hash="sha256:" + "a" * 64,
)


def _document(outcome: str, **fields: object) -> str:
    base = {"schema_version": 1, "outcome": outcome, "status": None}
    return json.dumps(base | {"stored_content_hash": None, "body_verified": None} | fields)


def _exporter(tmp_path: Path, stdout: str, *, code: int = 0, delay: float = 0) -> Path:
    """A stand-in exporter recording argv, env and stdin, then answering."""
    script = tmp_path / "exporter"
    (tmp_path / "answer").write_text(stdout)
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/argv"\n'
        f'env > "{tmp_path}/env"\n'
        f'cat > "{tmp_path}/stdin"\n'
        f"sleep {delay}\n"
        f'cat "{tmp_path}/answer"\n'
        f"exit {code}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _sink(binary: Path, *, timeout: float = 5) -> ExporterArchiveSink:
    return ExporterArchiveSink(
        ExporterConfirmConfig(
            binary=binary,
            store_url="https://seshmagic.test",
            token=SecretStr("read-token"),
            timeout_seconds=timeout,
        )
    )


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (
            _document("confirmed", status=200, stored_content_hash=_STORED, body_verified=True),
            RevisionConfirmed(stored_content_hash=_STORED, body_verified=True),
        ),
        (_document("absent", status=404), RevisionAbsent()),
        (_document("unauthorized", status=403), ConfirmUnauthorized(status=403)),
        (_document("integrity_failure", status=409), RevisionIntegrityFailure()),
        (_document("unavailable", status=503), ArchiveUnavailable()),
        (_document("unavailable"), ArchiveUnavailable()),
        (_document("not_advertised", status=404), ConfirmNotAdvertised()),
        (_document("unexpected", status=500), ConfirmUnexpectedResponse(status=500)),
        # Outside the CLI contract: never absent, never confirmed.
        (_document("confirmed", status=200), ConfirmUnexpectedResponse(status=200)),
        (_document("absent", extra=1), ConfirmUnexpectedResponse(status=0)),
        (_document("gone"), ConfirmUnexpectedResponse(status=0)),
        (_document("absent", schema_version=2), ConfirmUnexpectedResponse(status=0)),
        (
            _document("confirmed", status=200, stored_content_hash="sha256:x", body_verified=True),
            ConfirmUnexpectedResponse(status=0),
        ),
        ("not json", ConfirmUnexpectedResponse(status=0)),
        ("", ConfirmUnexpectedResponse(status=0)),
    ],
)
async def test_each_exporter_document_maps_to_exactly_one_outcome(
    tmp_path: Path, stdout: str, expected: RevisionConfirmation
) -> None:
    assert await _sink(_exporter(tmp_path, stdout)).confirm(_REVISION) == expected


@pytest.mark.parametrize("code", [1, 2, 3])
async def test_an_exporter_error_exit_is_unavailable_not_absent(tmp_path: Path, code: int) -> None:
    binary = _exporter(tmp_path, _document("absent", status=404), code=code)
    assert await _sink(binary).confirm(_REVISION) == ArchiveUnavailable()


async def test_a_missing_or_hung_exporter_is_unavailable(tmp_path: Path) -> None:
    assert await _sink(tmp_path / "absent").confirm(_REVISION) == ArchiveUnavailable()
    hung = _exporter(tmp_path, _document("absent"), delay=5)
    assert await _sink(hung, timeout=0.5).confirm(_REVISION) == ArchiveUnavailable()


async def test_asks_the_exporter_for_the_uploaded_revision_with_a_read_token(
    tmp_path: Path,
) -> None:
    await _sink(_exporter(tmp_path, _document("absent"))).confirm(_REVISION)
    assert (tmp_path / "argv").read_text().split() == ["--capture-confirm"]
    assert json.loads((tmp_path / "stdin").read_text()) == {
        "identity": {
            "source_instance_id": "install-1",
            "harness": "claude",
            "native_session_id": "native-1",
        },
        "content_hash": _REVISION.content_hash,
    }
    env = dict(line.split("=", 1) for line in (tmp_path / "env").read_text().splitlines())
    assert env["CAPTURE_READ_TOKEN"] == "read-token"
    assert env["SESSION_STORE_URL"] == "https://seshmagic.test"
    assert "CAPTURE_WRITE_TOKEN" not in env
    assert "INVENTORY_WRITE_TOKEN" not in env


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
    decision = await gate.decide([_revision(1), _revision(2)])
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
    decision = await gate.decide([_revision(1), _revision(2)])
    assert decision.hold is hold
    assert not decision.permitted
    assert gate.holds[hold] == 1


async def test_without_backup_attestation_nothing_is_permitted_or_asked() -> None:
    sink = _ScriptedSink({_revision(1).content_hash: _CONFIRMED})
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=False)
    decision = await gate.decide([_revision(1)])
    assert decision.hold is ExpiryHold.NO_BACKUP_ATTESTATION
    assert sink.asked == []


@pytest.mark.parametrize(
    "hold", [ExpiryHold.OLDER_REVISION, ExpiryHold.NOT_UPLOADED, ExpiryHold.SPLICE_BASE]
)
async def test_an_ineligible_body_is_held_without_asking(hold: ExpiryHold) -> None:
    sink = _ScriptedSink({_revision(1).content_hash: _CONFIRMED})
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=True)
    assert (await gate.decide([_revision(1)], ineligible=hold)).hold is hold
    assert (await gate.decide([])).hold is ExpiryHold.NOT_UPLOADED
    assert sink.asked == []


async def test_a_slow_archive_cannot_delay_reconciliation() -> None:
    release = asyncio.Event()
    drains = 0

    async def slow_drain() -> int:
        nonlocal drains
        drains += 1
        await release.wait()
        return 0

    retention = AsyncMock()
    retention.drain.side_effect = slow_drain
    lane = RetentionLane(retention)
    scheduler = AsyncMock()
    work = InventoryWork(scheduler=scheduler, step=AsyncMock(), retention_lane=lane)
    await asyncio.wait_for(work.schedule(), timeout=1)
    await asyncio.wait_for(work.schedule(), timeout=1)
    await asyncio.sleep(0)
    assert scheduler.handle.await_count == 2
    assert drains == 1  # one drain in flight per process
    release.set()
    await asyncio.sleep(0.01)
    await work.schedule()
    await asyncio.sleep(0)
    assert drains == 2
    await lane.stop()


async def test_a_failing_drain_is_logged_by_type_and_retried_next_tick(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retention = AsyncMock()
    retention.drain.side_effect = [OSError("/private/archive/secret"), 0]
    lane = RetentionLane(retention)
    lane.schedule()
    await asyncio.sleep(0.01)
    assert "OSError" in caplog.text and "/private/archive" not in caplog.text
    lane.schedule()
    await asyncio.sleep(0.01)
    assert retention.drain.await_count == 2
    await lane.stop()
    lane.schedule()
    assert retention.drain.await_count == 2


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
        replication_store_url="https://seshmagic.test",
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
