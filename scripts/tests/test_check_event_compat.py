"""The compat gate's rule: unreadable by the release is excused only by a higher epoch.

``just check-event-compat`` itself is the evidence against a real release
(#1310 V9). No release tagged so far carries an Event Epoch, so the branch where
a bump excuses an unreadable payload can only be reached here: the release's
answer is substituted, and ``check`` - the consumer of the epoch - decides.
The fixture-suite tests guard the other way to a false green: a suite that
tests nothing must stop the check before any release is built.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_event_compat
from check_event_compat import (
    CompatCheckError,
    EventIdentity,
    Fixture,
    ProbeRequest,
    ReleaseAnswer,
    ReleaseRead,
    ReleaseWrite,
    check,
    load_fixtures,
)
from event_compat import probe

from syn_domain.contexts.orchestration._shared import event_epoch
from syn_domain.contexts.orchestration.domain.events import (
    PhaseStartedEvent,
    WorkflowExecutionStartedEvent,
)

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


_PHASE = Fixture(
    name="phase_started",
    event="PhaseStartedEvent",
    payload={
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "phase_id": "p-1",
        "phase_name": "implement",
        "phase_order": 1,
        "started_at": "2026-10-14T09:00:00Z",
    },
)

_START_ID = EventIdentity.of(WorkflowExecutionStartedEvent)
_PHASE_ID = EventIdentity.of(PhaseStartedEvent)

#: What v1.0.0's PhaseStartedEvent writes for _PHASE: its own default, ``session_id: null``.
_OLD_PHASE_WRITE = ReleaseWrite(identity=_PHASE_ID, payload={**_PHASE.payload, "session_id": None})

_START_WRITE = ReleaseWrite(identity=_START_ID, payload=_START.payload)
_READABLE = ReleaseRead(written=_START_WRITE)


def _release_answers(
    monkeypatch: pytest.MonkeyPatch, *, epoch: int | None, result: ReleaseRead
) -> list[ProbeRequest]:
    seen: list[ProbeRequest] = []

    def fake(_python: Path, requests: list[ProbeRequest], _workdir: Path) -> ReleaseAnswer:
        seen.extend(requests)
        return ReleaseAnswer(epoch=epoch, results={r.name: result for r in requests})

    monkeypatch.setattr(check_event_compat, "_ask_release", fake)
    return seen


def _verdict(tmp_path: Path, fixture: Fixture = _START) -> str | None:
    [verdict] = check("vX", Path("python"), [fixture], tmp_path)
    return verdict.problem


def test_unreadable_payload_fails_when_the_epoch_was_not_bumped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(
        monkeypatch,
        epoch=event_epoch.ORCHESTRATION_EVENT_EPOCH,
        result=ReleaseRead(read_error="extra_forbidden", written=_START_WRITE),
    )
    problem = _verdict(tmp_path)
    assert problem is not None
    assert "cannot read what this tree writes" in problem


def test_unreadable_payload_passes_when_the_epoch_is_above_the_releases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(
        monkeypatch,
        epoch=1,
        result=ReleaseRead(read_error="extra_forbidden", written=_START_WRITE),
    )
    monkeypatch.setattr(event_epoch, "ORCHESTRATION_EVENT_EPOCH", 2)
    assert _verdict(tmp_path) is None


def test_a_release_with_no_epoch_has_no_claim_guard_so_no_bump_excuses_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(
        monkeypatch,
        epoch=None,
        result=ReleaseRead(read_error="extra_forbidden", written=_START_WRITE),
    )
    monkeypatch.setattr(event_epoch, "ORCHESTRATION_EVENT_EPOCH", 99)
    assert _verdict(tmp_path) is not None


def test_what_the_release_writes_back_must_be_readable_even_after_a_bump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A guarded forward rejection must not skip the backward direction (verify R1)."""
    _release_answers(
        monkeypatch,
        epoch=1,
        result=ReleaseRead(read_error="extra_forbidden", written=_OLD_PHASE_WRITE),
    )
    monkeypatch.setattr(event_epoch, "ORCHESTRATION_EVENT_EPOCH", 2)
    monkeypatch.setattr(check_event_compat, "_current_decoder", lambda _id: _DefaultedSession)
    problem = _verdict(tmp_path, _PHASE)
    assert problem is not None
    assert "cannot read what vX writes" in problem


def test_the_release_is_sent_what_this_tree_writes_not_the_raw_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _release_answers(monkeypatch, epoch=None, result=_READABLE)
    _verdict(tmp_path)
    [sent] = seen
    # The fixture omits expected_completion_at; the model's serializer writes it.
    assert "expected_completion_at" not in _START.payload
    assert "expected_completion_at" in sent.current


def test_the_release_writes_the_fixture_itself_not_this_trees_serialization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The backward payload must be the old writer's own, not an echo of ours (verify R1)."""
    seen = _release_answers(monkeypatch, epoch=None, result=_READABLE)
    _verdict(tmp_path)
    [sent] = seen
    assert sent.fixture == _START.payload


class _DefaultedSession(BaseModel, frozen=True, extra="forbid"):
    """PhaseStartedEvent with ``session_id: str | None = None`` turned into ``str = "new"``."""

    workflow_id: str
    execution_id: str
    phase_id: str
    phase_name: str
    phase_order: int
    started_at: str
    session_id: str = "new-session"


def test_an_old_nullable_default_fails_a_defaulted_non_nullable_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The release writes ``session_id: null`` for a fixture that omits it (verify R1)."""
    _release_answers(monkeypatch, epoch=None, result=ReleaseRead(written=_OLD_PHASE_WRITE))
    monkeypatch.setattr(check_event_compat, "_current_decoder", lambda _id: _DefaultedSession)
    problem = _verdict(tmp_path, _PHASE)
    assert problem is not None
    assert "session_id" in problem


def test_a_release_that_can_write_no_fixture_cannot_certify_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _release_answers(
        monkeypatch, epoch=1, result=ReleaseRead(read_error="x", write_error="extra_forbidden")
    )
    monkeypatch.setattr(event_epoch, "ORCHESTRATION_EVENT_EPOCH", 2)
    with pytest.raises(CompatCheckError, match="backward direction went untested"):
        _verdict(tmp_path)


@pytest.mark.parametrize(
    ("stored_as", "why"),
    [
        (_START_ID.model_copy(update={"event_type": "WorkflowExecutionBegan"}), "no Workflow"),
        (_START_ID.model_copy(update={"schema_version": 2}), "schema_version 2"),
        (_START_ID.model_copy(update={"version": "v2"}), "'v2'"),
    ],
    ids=["renamed-type", "bumped-schema-version", "bumped-event-version"],
)
def test_what_the_release_stores_under_another_identity_is_unreadable_here(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stored_as: EventIdentity, why: str
) -> None:
    """The store decodes by type and version, so a valid payload alone is not enough."""
    written = ReleaseWrite(identity=stored_as, payload=_START.payload)
    _release_answers(monkeypatch, epoch=None, result=ReleaseRead(written=written))
    problem = _verdict(tmp_path)
    assert problem is not None
    assert "cannot read what vX writes" in problem
    assert why in problem


def test_the_release_is_told_the_identity_this_tree_stores_the_event_under(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _release_answers(monkeypatch, epoch=None, result=_READABLE)
    _verdict(tmp_path)
    [sent] = seen
    assert sent.identity == EventIdentity(
        event_type="WorkflowExecutionStarted", version="v1", schema_version=1
    )


# The probe itself, run here against this tree standing in for the release.


def _probe_request(identity: EventIdentity, current: dict[str, object]) -> dict[str, object]:
    return {
        "name": _PHASE.name,
        "event": _PHASE.event,
        "identity": identity.model_dump(),
        "current": current,
        "fixture": _PHASE.payload,
    }


def test_the_probe_writes_the_fixture_not_what_this_tree_wrote() -> None:
    """Kills "the backward direction reads ``current``" (verify M5)."""
    current = {**_PHASE.payload, "phase_id": "written-by-this-tree"}
    answer = probe._answer(_probe_request(_PHASE_ID, current))
    assert answer["read_error"] is None
    assert answer["written"] == {
        "identity": _PHASE_ID.model_dump(),
        "payload": PhaseStartedEvent.model_validate(_PHASE.payload).model_dump(mode="json"),
    }


@pytest.mark.parametrize(
    ("stored_as", "why"),
    [
        (_PHASE_ID.model_copy(update={"event_type": "PhaseRenamedAway"}), "cannot decode PhaseRenamedAway"),
        (_PHASE_ID.model_copy(update={"schema_version": 99}), "schema_version 99"),
        (_PHASE_ID.model_copy(update={"version": "v99"}), "'v99'"),
    ],
    ids=["renamed-type", "bumped-schema-version", "bumped-event-version"],
)
def test_the_probe_cannot_read_an_event_stored_under_an_identity_it_does_not_know(
    stored_as: EventIdentity, why: str
) -> None:
    answer = probe._answer(_probe_request(stored_as, _PHASE.payload))
    assert isinstance(answer["read_error"], str)
    assert why in answer["read_error"]


def _suite(tmp_path: Path, content: object) -> Path:
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(content), "utf-8")
    return path


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ({}, "not a list"),
        ([], "is empty"),
        ([{"name": "x"}], "malformed fixture"),
        ([_PHASE.model_dump(), _PHASE.model_dump()], "repeats a fixture name"),
        ([_PHASE.model_dump()], "non-empty tags"),
        (
            [_START.model_copy(update={"payload": {**_START.payload, "tags": []}}).model_dump()],
            "non-empty tags",
        ),
    ],
    ids=["object", "empty", "malformed", "duplicate", "no-tagged-start", "empty-tags"],
)
def test_a_suite_that_tests_nothing_cannot_run(
    tmp_path: Path, content: object, reason: str
) -> None:
    with pytest.raises(CompatCheckError, match=reason):
        load_fixtures(_suite(tmp_path, content))


def test_a_bad_suite_stops_before_any_release_is_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def built(*_args: object) -> Path:
        pytest.fail("a release environment was built for an unusable fixture suite")

    monkeypatch.setattr(check_event_compat, "FIXTURES", _suite(tmp_path, {}))
    monkeypatch.setattr(check_event_compat, "build_release_env", built)
    monkeypatch.setattr(check_event_compat, "previous_release", lambda _tag: "vX")
    monkeypatch.setattr(sys, "argv", ["check_event_compat.py"])
    assert check_event_compat.main() == 2


def test_the_checked_in_suite_loads() -> None:
    fixtures = load_fixtures(check_event_compat.FIXTURES)
    assert any(f.name == "tagged_start" for f in fixtures)
