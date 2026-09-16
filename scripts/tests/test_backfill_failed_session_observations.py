"""The backfill is the fifth writer into ``agent_events``, and it was unguarded.

Every live write into that table passes its text through ``postgres_text``
first, because an agent can emit a codepoint Postgres cannot store and the
resulting failure is not scoped to the one field - it takes down the write
(#1241, #781). This script writes the same untrusted text into the same columns:
``error_message`` is whatever the agent said on its way out, and ``session_id``
comes from the harness. It reached the driver through a bare ``json.dumps``.

The failure mode a backfill adds on top: it writes every orphaned session in one
loop, so a single hostile row does not lose its own observation, it stops the
run at that row and leaves the rest unwritten.

Driven with a real chr(0) and a real lone surrogate, not the six-character text
that spells one - a near-miss passes against unsanitised code and would certify
this closed while it is open.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    import asyncpg

# scripts/backfill is not a package and is not on pythonpath; the sibling
# script tests reach their subject the same way.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backfill"))

from backfill_failed_session_observations import _observation

pytestmark = pytest.mark.unit

NUL = chr(0)
LONE_SURROGATE = chr(0xDEAD)

#: What the dying agent wrote to stderr, as the event carries it.
HOSTILE_ERROR = "Traceback" + NUL + ": exit 1 " + LONE_SURROGATE
#: ...and what must still be readable afterwards. Nothing but the two go.
CLEANED_ERROR = "Traceback: exit 1 "

STARTED_AT = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)


def _row(**overrides: object) -> asyncpg.Record:
    """One row as ``_ORPHANS_QUERY`` returns it.

    A Record is read by key and cannot be constructed outside the driver, so the
    test supplies the one thing the function actually uses of it.
    """
    values: dict[str, object] = {
        "started_at": STARTED_AT,
        "session_id": "sess-1",
        "execution_id": "exec-1",
        "phase_id": "implement",
        "status": "failed",
        "error_message": None,
        "model": "claude-opus-5",
    }
    values.update(overrides)
    return cast("asyncpg.Record", values)


def test_hostile_error_message_is_stored_and_still_legible() -> None:
    observation = _observation(_row(error_message=HOSTILE_ERROR))

    observation.data_json.encode("utf-8")  # a lone surrogate has no encoding
    data = json.loads(observation.data_json)  # exactly what ::jsonb is handed
    assert NUL not in data["error_message"], "jsonb would refuse this row"
    assert data["error_message"] == CLEANED_ERROR, "sanitised into oblivion"


def test_hostile_ids_are_stored_as_the_live_path_stores_them() -> None:
    """A backfilled row must be findable under the id the live writer would use."""
    observation = _observation(
        _row(
            session_id="sess" + NUL + "-1",
            execution_id="exec" + LONE_SURROGATE + "-1",
            phase_id="implement" + NUL,
        )
    )

    for value in (observation.session_id, observation.execution_id, observation.phase_id):
        assert value is not None
        value.encode("utf-8")
        assert NUL not in value
    assert observation.session_id == "sess-1"
    assert observation.execution_id == "exec-1"
    assert observation.phase_id == "implement"


def test_the_row_keeps_saying_what_it_said() -> None:
    """Sanitising must not be a licence to drop or reshape the record."""
    observation = _observation(_row(error_message="setup failed"))

    assert observation.started_at == STARTED_AT, "attributed to the wrong instant"
    assert json.loads(observation.data_json) == {
        "status": "failed",
        "error_message": "setup failed",
        "model": "claude-opus-5",
        "backfilled": True,
    }


def test_a_session_that_never_started_still_gets_written() -> None:
    """The LEFT JOIN yields NULL attribution; None must survive as None."""
    observation = _observation(_row(execution_id=None, phase_id=None, model=None))

    assert observation.execution_id is None
    assert observation.phase_id is None
    assert json.loads(observation.data_json)["model"] is None
