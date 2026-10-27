"""#2107 slice 3: older revisions stored as verified slices of the newest."""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from typing import TYPE_CHECKING

import pytest

from syn_adapters.session_inventory.archive_splice import (
    SpliceReference,
    envelope_identity,
    plan_splice,
    reconstruct,
)
from syn_adapters.session_inventory.local_archive import (
    LocalSessionTranscriptArchive,
    SpliceStatus,
)
from syn_domain.contexts.agent_sessions import ArchivedTranscript, TranscriptIntegrityError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _lines(count: int) -> str:
    # Distinct lines, so gzip cannot make an object smaller than its reference.
    return "".join(
        f'{{"type":"assistant","n":{n},"text":"a \\"quoted\\" {hashlib.sha256(str(n).encode()).hexdigest()}"}}\n'
        for n in range(count)
    )


def _envelope(lines: int, *, session: str = "s-1", seen: str = "") -> bytes:
    """A capture envelope as the exporter writes it: ``raw`` last, head varies per revision."""
    return json.dumps(
        {
            "scs_version": "1.0",
            "agent": "ClaudeCode",
            "session_id": session,
            "last_activity_at": seen or f"2026-10-26T00:{lines:02d}:00Z",
            "metadata": {"message_count": lines, "raw": "nested key, not the body"},
            "raw": _lines(lines),
        },
        separators=(",", ":"),
    ).encode()


def _ref(body: bytes) -> ArchivedTranscript:
    return ArchivedTranscript(sha256=hashlib.sha256(body).hexdigest(), size=len(body))


def test_plan_reconstructs_exactly_and_refuses_what_is_not_a_prefix() -> None:
    older, newest = _envelope(40), _envelope(90)
    plan = plan_splice(older, newest)
    assert plan is not None and reconstruct(plan, newest) == older
    assert len(plan.head) + len(plan.tail) < 300 and plan.length > 40 * 100
    assert plan_splice(older.replace(b"assistant", b"assistanT"), newest) is None
    # Plain append-only bytes (a native transcript) splice with no head or tail.
    native = plan_splice(b"line 1\n", b"line 1\nline 2\n")
    assert native is not None and native.head == b"" and native.tail == b""


def test_reconstruct_rejects_any_damaged_field() -> None:
    older, newest = _envelope(40), _envelope(90)
    plan = plan_splice(older, newest)
    assert plan is not None
    for damaged in (
        plan.model_copy(update={"offset": plan.offset + 1}),
        plan.model_copy(update={"length": plan.length - 1}),
        plan.model_copy(update={"head": plan.head[:-1] + b"X"}),
        plan.model_copy(update={"base_size": plan.base_size + 1}),
    ):
        assert reconstruct(damaged, newest) is None
    inside = plan.offset + 10
    flipped = newest[:inside] + bytes([newest[inside] ^ 1]) + newest[inside + 1 :]
    assert reconstruct(plan, flipped) is None


def test_identity_reads_the_head_only() -> None:
    assert envelope_identity(_envelope(3)[:200]) == ("ClaudeCode", "s-1")
    assert envelope_identity(b"line 1\n") is None


async def test_splice_measures_then_stores_a_verified_reference(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older, newest = await archive.put(_envelope(40)), await archive.put(_envelope(90))
    dry = archive.splice_onto(older.sha256, newest.sha256, apply=False)
    assert dry.status is SpliceStatus.SPLICED and dry.after < dry.before
    assert (tmp_path / older.sha256).exists()
    assert not list(tmp_path.glob(".ref-*")) and not list(tmp_path.glob(".pin-*"))
    applied = archive.splice_onto(older.sha256, newest.sha256, apply=True)
    assert applied == dry
    assert not (tmp_path / older.sha256).exists()
    assert (tmp_path / f".pin-{newest.sha256}-{older.sha256}").exists()
    assert await LocalSessionTranscriptArchive(tmp_path).get(older) == _envelope(40)
    assert await archive.get(newest) == _envelope(90)
    again = archive.splice_onto(older.sha256, newest.sha256, apply=True)
    assert again.status is SpliceStatus.ALREADY_REFERENCED
    assert sorted(archive.object_keys()) == [newest.sha256]
    assert not list(tmp_path.glob(".reference-*"))


async def test_uncompressed_base_and_plain_prefix_splice(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path, compress=False)
    older, newest = await archive.put(b"line 1\n" * 50), await archive.put(b"line 1\n" * 90)
    outcome = archive.splice_onto(older.sha256, newest.sha256, apply=True)
    assert outcome.status is SpliceStatus.SPLICED
    assert await archive.get(older) == b"line 1\n" * 50


async def test_a_revision_that_does_not_fit_stays_a_full_object(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older = await archive.put(_envelope(40).replace(b"assistant", b"assistanT"))
    newest = await archive.put(_envelope(90))
    outcome = archive.splice_onto(older.sha256, newest.sha256, apply=True)
    assert outcome.status is SpliceStatus.NOT_A_PREFIX
    assert (tmp_path / older.sha256).exists() and not list(tmp_path.glob(".ref-*"))
    assert not list(tmp_path.glob(".pin-*"))


async def test_every_read_reverifies_and_fails_loudly(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older, newest = await archive.put(_envelope(40)), await archive.put(_envelope(90))
    archive.splice_onto(older.sha256, newest.sha256, apply=True)
    reference_path = tmp_path / f".ref-{older.sha256}"
    good = reference_path.read_bytes()
    shifted = SpliceReference.model_validate_json(good)
    reference_path.write_text(
        shifted.model_copy(update={"offset": shifted.offset + 1}).model_dump_json()
    )
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(older)
    reference_path.write_bytes(b"{not json")
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(older)
    reference_path.write_bytes(good)
    base_path = tmp_path / newest.sha256
    base_path.write_bytes(gzip.compress(_envelope(90).replace(b"assistant", b"assistanT")))
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(older)
    base_path.unlink()
    # A missing base is damage, never "absent".
    with pytest.raises(TranscriptIntegrityError):
        await archive.get(older)


async def test_a_reference_is_never_a_base(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    a, b, c = [await archive.put(_envelope(n)) for n in (10, 20, 30)]
    archive.splice_onto(b.sha256, c.sha256, apply=True)
    outcome = archive.splice_onto(a.sha256, b.sha256, apply=True)
    assert outcome.status is SpliceStatus.INELIGIBLE
    assert (tmp_path / a.sha256).exists()
    with pytest.raises(ValueError, match="itself"):
        archive.splice_onto(a.sha256, a.sha256, apply=True)


async def test_a_reference_whose_full_object_a_crash_left_is_never_a_base(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    a, b, c = [await archive.put(_envelope(n)) for n in (10, 20, 30)]
    stored = (tmp_path / b.sha256).read_bytes()
    archive.splice_onto(b.sha256, c.sha256, apply=True)
    # A crash after the reference committed, before the full object was unlinked.
    (tmp_path / b.sha256).write_bytes(stored)
    assert archive.splice_onto(a.sha256, b.sha256, apply=True).status is SpliceStatus.INELIGIBLE
    assert (tmp_path / a.sha256).exists()


async def test_deleting_a_base_with_a_damaged_referrer_fails_without_losing_it(
    tmp_path: Path,
) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older, newest = await archive.put(_envelope(40)), await archive.put(_envelope(90))
    archive.splice_onto(older.sha256, newest.sha256, apply=True)
    reference_path = tmp_path / f".ref-{older.sha256}"
    good = reference_path.read_bytes()
    shifted = SpliceReference.model_validate_json(good)
    reference_path.write_text(
        shifted.model_copy(update={"offset": shifted.offset + 1}).model_dump_json()
    )
    with pytest.raises(TranscriptIntegrityError):
        await archive.delete(newest)
    # Nothing was materialised from unverified bytes, and the referrer is recoverable.
    assert reference_path.exists() and (tmp_path / newest.sha256).exists()
    reference_path.write_bytes(good)
    assert await archive.get(older) == _envelope(40)


async def test_splicing_a_base_retargets_its_referrers_first(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    first, middle = await archive.put(_envelope(10)), await archive.put(_envelope(20))
    archive.splice_onto(first.sha256, middle.sha256, apply=True)
    newest = await archive.put(_envelope(30))
    outcome = archive.splice_onto(middle.sha256, newest.sha256, apply=True)
    assert outcome.status is SpliceStatus.SPLICED and outcome.retargeted == 1
    for reference in (first, middle):
        moved = SpliceReference.model_validate_json(
            (tmp_path / f".ref-{reference.sha256}").read_bytes()
        )
        assert moved.base_sha256 == newest.sha256
    assert sorted(p.name for p in tmp_path.glob(".pin-*")) == sorted(
        f".pin-{newest.sha256}-{r.sha256}" for r in (first, middle)
    )
    assert sorted(archive.object_keys()) == [newest.sha256]
    assert await archive.get(first) == _envelope(10)
    assert await archive.get(middle) == _envelope(20)


async def test_a_base_whose_referrer_cannot_move_stays_full(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    middle_body = _envelope(20)
    first_body = middle_body[: len(middle_body) // 2]  # a byte prefix, not an envelope
    first, middle = await archive.put(first_body), await archive.put(middle_body)
    assert (
        archive.splice_onto(first.sha256, middle.sha256, apply=True).status is SpliceStatus.SPLICED
    )
    newest = await archive.put(_envelope(30))
    outcome = archive.splice_onto(middle.sha256, newest.sha256, apply=True)
    assert outcome.status is SpliceStatus.NOT_A_PREFIX
    assert (tmp_path / middle.sha256).exists()
    assert not list(tmp_path.glob(f".pin-{newest.sha256}-*"))
    assert await archive.get(first) == first_body


async def test_reference_commits_before_the_full_object_is_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older, newest = await archive.put(_envelope(40)), await archive.put(_envelope(90))

    def crash(*_args: object) -> None:
        raise OSError("killed while publishing the reference")

    monkeypatch.setattr(archive, "_replace_locked", crash)
    with pytest.raises(OSError, match="killed"):
        archive.splice_onto(older.sha256, newest.sha256, apply=True)
    monkeypatch.undo()
    assert (tmp_path / older.sha256).exists()
    assert await archive.get(older) == _envelope(40)
    # The re-run finishes from the pin the crash left.
    assert (
        archive.splice_onto(older.sha256, newest.sha256, apply=True).status is SpliceStatus.SPLICED
    )
    assert await archive.get(older) == _envelope(40)


async def test_deleting_a_base_turns_its_referrers_back_into_full_objects(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older, newest = await archive.put(_envelope(40)), await archive.put(_envelope(90))
    archive.splice_onto(older.sha256, newest.sha256, apply=True)
    await archive.mark_deleted(newest)
    assert await archive.get(older) == _envelope(40)  # a tombstoned base still serves slices
    await archive.delete(newest)
    assert await archive.get(newest) is None
    assert (tmp_path / older.sha256).exists()
    assert not list(tmp_path.glob(".ref-*")) and not list(tmp_path.glob(".pin-*"))
    assert await archive.get(older) == _envelope(40)


async def test_deleting_a_referrer_removes_its_reference_and_pin(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older, newest = await archive.put(_envelope(40)), await archive.put(_envelope(90))
    archive.splice_onto(older.sha256, newest.sha256, apply=True)
    await archive.delete(older)
    assert await archive.get(older) is None
    assert not list(tmp_path.glob(".ref-*")) and not list(tmp_path.glob(".pin-*"))
    assert await archive.get(newest) == _envelope(90)
    await archive.delete(newest)  # nothing left pinning it


async def test_deleted_revisions_are_never_spliced(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    older, newest = await archive.put(_envelope(40)), await archive.put(_envelope(90))
    await archive.mark_deleted(older)
    assert (
        archive.splice_onto(older.sha256, newest.sha256, apply=True).status
        is SpliceStatus.INELIGIBLE
    )
    other = await archive.put(_envelope(50))
    await archive.mark_deleted(newest)
    assert (
        archive.splice_onto(other.sha256, newest.sha256, apply=True).status
        is SpliceStatus.INELIGIBLE
    )
    assert (tmp_path / other.sha256).exists()


async def test_two_digests_on_one_lock_stripe_do_not_deadlock(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)
    newest = _envelope(90)
    stripe = hashlib.sha256(newest).hexdigest()[:2]
    older = next(
        body
        for body in (_envelope(40, seen=f"2026-10-26T{n}") for n in range(100_000))
        if hashlib.sha256(body).hexdigest()[:2] == stripe
    )
    references = await archive.put(older), await archive.put(newest)
    done: list[SpliceStatus] = []
    worker = threading.Thread(
        target=lambda: done.append(
            archive.splice_onto(references[0].sha256, references[1].sha256, apply=True).status
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=20)
    assert done == [SpliceStatus.SPLICED]


async def test_envelope_summary_reads_identity_and_size(tmp_path: Path) -> None:
    compressed = LocalSessionTranscriptArchive(tmp_path)
    ref = await compressed.put(_envelope(40))
    summary = compressed.envelope_summary(ref.sha256)
    assert summary is not None and (summary.agent, summary.session_id) == ("ClaudeCode", "s-1")
    assert summary.size == len(_envelope(40))
    plain = await LocalSessionTranscriptArchive(tmp_path, compress=False).put(_envelope(41))
    assert compressed.envelope_summary(plain.sha256) is not None
    native = await compressed.put(b"line 1\n")
    assert compressed.envelope_summary(native.sha256) is None


async def test_a_reference_larger_than_the_object_is_not_written(tmp_path: Path) -> None:
    archive = LocalSessionTranscriptArchive(tmp_path)

    def small(raw: str) -> bytes:
        return json.dumps({"agent": "ClaudeCode", "raw": raw}, separators=(",", ":")).encode()

    older, newest = await archive.put(small("a" * 400)), await archive.put(small("a" * 900))
    outcome = archive.splice_onto(older.sha256, newest.sha256, apply=True)
    assert outcome.status is SpliceStatus.NO_SAVING
    assert (tmp_path / older.sha256).exists() and not list(tmp_path.glob(".ref-*"))
