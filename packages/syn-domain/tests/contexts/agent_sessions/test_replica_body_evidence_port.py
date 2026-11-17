"""Remote PRESENT needs a read of the stored body, not an echoed hash (#946).

The rows are synthetic: sizes only, in the shapes #946 measured. What a real
store row looks like belongs to the exporter that reads it.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions import BodyAvailability
from syn_domain.contexts.agent_sessions.ports.QualifiedSessionStorePort import (
    QualifiedSessionIdentity,
)
from syn_domain.contexts.agent_sessions.ports.ReplicaBodyEvidencePort import (
    ReplicaBodyReading,
    replica_body_availability,
)

pytestmark = pytest.mark.unit

IDENTITY = QualifiedSessionIdentity(
    kind="transcript", source_instance_id="host", harness="codex", local_id="native"
)
REVISION = "sha256:" + "a" * 64


def _reading(raw: int, search: int, messages: int) -> ReplicaBodyReading:
    return ReplicaBodyReading(
        identity=IDENTITY,
        revision=REVISION,
        raw_bytes=raw,
        search_text_bytes=search,
        message_count=messages,
    )


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        pytest.param(_reading(0, 21, 14), BodyAvailability.MISSING, id="codex-raw-missing"),
        pytest.param(_reading(0, 0, 651), BodyAvailability.MISSING, id="claude-nothing-extracted"),
        pytest.param(None, BodyAvailability.MISSING, id="revision-absent"),
        pytest.param(_reading(20, 21, 14), BodyAvailability.PRESENT, id="real-body"),
    ],
)
def test_only_a_stored_raw_body_is_present(
    reading: ReplicaBodyReading | None, expected: BodyAvailability
) -> None:
    assert replica_body_availability(reading, IDENTITY, REVISION, archived_bytes=52) is expected


def test_reading_for_another_revision_is_refused() -> None:
    with pytest.raises(ValueError, match="another transcript revision"):
        replica_body_availability(
            _reading(20, 21, 14), IDENTITY, "sha256:" + "e" * 64, archived_bytes=52
        )
