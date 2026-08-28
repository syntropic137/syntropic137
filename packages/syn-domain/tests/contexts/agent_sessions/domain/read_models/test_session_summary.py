"""Round-trip tests for SessionSummary parent/root session linkage (#792).

SessionSummary round-trips through THREE places: the field declaration,
``from_dict``, and ``to_dict``. A field added to only two of the three
vanishes silently - this guards that hot spot.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary,
)


@pytest.mark.unit
def test_parent_session_id_survives_round_trip() -> None:
    """parent_session_id and root_session_id survive a to_dict/from_dict cycle."""
    summary = SessionSummary(
        id="child-1",
        workflow_id="wf-1",
        agent_type="claude",
        status="completed",
        total_tokens=0,
        started_at=None,
        completed_at=None,
        parent_session_id="parent-1",
        root_session_id="parent-1",
    )
    restored = SessionSummary.from_dict(summary.to_dict())
    assert restored.parent_session_id == "parent-1"
    assert restored.root_session_id == "parent-1"


@pytest.mark.unit
def test_parent_session_id_defaults_to_none_for_legacy_dict() -> None:
    """A legacy dict with neither key yields None for both (tolerant reader)."""
    legacy = {
        "id": "s",
        "workflow_id": "w",
        "agent_type": "claude",
        "status": "completed",
        "total_tokens": 0,
    }
    restored = SessionSummary.from_dict(legacy)
    assert restored.parent_session_id is None
    assert restored.root_session_id is None
