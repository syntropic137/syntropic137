"""The compat gate's rule: unreadable by the release is excused only by a higher epoch.

``just check-event-compat`` itself is the evidence against a real release
(#1310 V9). No release tagged so far carries an Event Epoch, so the branch where
a bump excuses an unreadable payload can only be reached here: the release's
answer is substituted, and ``check`` - the consumer of the epoch - decides.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_event_compat
from check_event_compat import Fixture, ReleaseAnswer, ReleaseRead, check

from syn_domain.contexts.orchestration._shared import event_epoch

pytestmark = pytest.mark.unit

_START = Fixture(
    name="tagged_start",
    event="WorkflowExecutionStartedEvent",
    payload={
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "workflow_name": "w",
        "started_at": "2026-10-14T09:00:00Z",
        "total_phases": 1,
        "inputs": {},
        "tags": ["phase-1"],
    },
)


def _release_answers(
    monkeypatch: pytest.MonkeyPatch, *, epoch: int | None, result: ReleaseRead
) -> list[Fixture]:
    seen: list[Fixture] = []

    def fake(_python: Path, fixtures: list[Fixture], _workdir: Path) -> ReleaseAnswer:
        seen.extend(fixtures)
        return ReleaseAnswer(epoch=epoch, results={f.name: result for f in fixtures})

    monkeypatch.setattr(check_event_compat, "_ask_release", fake)
    return seen


def _verdict(tmp_path: Path) -> str | None:
    [verdict] = check("vX", Path("python"), [_START], tmp_path)
    return verdict.problem


def test_unreadable_payload_fails_when_the_epoch_was_not_bumped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(
        monkeypatch,
        epoch=event_epoch.ORCHESTRATION_EVENT_EPOCH,
        result=ReleaseRead(error="extra_forbidden"),
    )
    problem = _verdict(tmp_path)
    assert problem is not None
    assert "cannot read what this tree writes" in problem


def test_unreadable_payload_passes_when_the_epoch_is_above_the_releases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(monkeypatch, epoch=1, result=ReleaseRead(error="extra_forbidden"))
    monkeypatch.setattr(event_epoch, "ORCHESTRATION_EVENT_EPOCH", 2)
    assert _verdict(tmp_path) is None


def test_a_release_with_no_epoch_has_no_claim_guard_so_no_bump_excuses_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(monkeypatch, epoch=None, result=ReleaseRead(error="extra_forbidden"))
    monkeypatch.setattr(event_epoch, "ORCHESTRATION_EVENT_EPOCH", 99)
    assert _verdict(tmp_path) is not None


def test_what_the_release_writes_back_must_be_readable_even_after_a_bump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(monkeypatch, epoch=1, result=ReleaseRead(written={"workflow_id": "wf-1"}))
    monkeypatch.setattr(event_epoch, "ORCHESTRATION_EVENT_EPOCH", 2)
    problem = _verdict(tmp_path)
    assert problem is not None
    assert "cannot read what vX writes" in problem


def test_the_release_is_sent_what_this_tree_writes_not_the_raw_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _release_answers(monkeypatch, epoch=None, result=ReleaseRead(written=_START.payload))
    _verdict(tmp_path)
    [sent] = seen
    # The fixture omits expected_completion_at; the model's serializer writes it.
    assert "expected_completion_at" not in _START.payload
    assert "expected_completion_at" in sent.payload
