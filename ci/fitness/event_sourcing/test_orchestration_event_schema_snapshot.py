"""Fitness function: no orchestration event schema changes without an epoch bump.

ADR-072 D9 (V13 in the #1310 plan). The type, version and schema of every
orchestration event must equal the snapshot recorded for the current
``ORCHESTRATION_EVENT_EPOCH``.
A whole-codebase static property, so it lives here and not beside one event.

The release-time half, which loads the previous release's models and parses
real payloads with them, is ``just check-event-compat``.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import pytest
from ci.fitness.event_sourcing._orchestration_event_schemas import (
    current_schemas,
    load_snapshot,
    snapshot_path,
)

from syn_domain.contexts.orchestration._shared.event_epoch import ORCHESTRATION_EVENT_EPOCH

_FIX = (
    "Bump ORCHESTRATION_EVENT_EPOCH in "
    "packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py, "
    "then run `uv run python -m ci.fitness.event_sourcing._orchestration_event_schemas` "
    "to snapshot the new epoch (ADR-072 D9)."
)


@pytest.mark.architecture
def test_orchestration_event_schemas_match_the_current_epoch_snapshot() -> None:
    snapshot = load_snapshot(ORCHESTRATION_EVENT_EPOCH)
    assert snapshot is not None, (
        f"No schema snapshot for Event Epoch {ORCHESTRATION_EVENT_EPOCH} "
        f"({snapshot_path(ORCHESTRATION_EVENT_EPOCH).name}). {_FIX}"
    )

    current = current_schemas()
    added = sorted(current.keys() - snapshot.keys())
    removed = sorted(snapshot.keys() - current.keys())
    changed = sorted(n for n in current.keys() & snapshot.keys() if current[n] != snapshot[n])

    assert not (added or removed or changed), (
        f"Orchestration event types, versions or schemas differ from Event Epoch "
        f"{ORCHESTRATION_EVENT_EPOCH}'s snapshot: changed={changed}, added={added}, "
        f"removed={removed}. An older Executor would claim runs whose events it "
        f"cannot read. {_FIX}"
    )


@pytest.mark.architecture
def test_a_bumped_epoch_changes_some_schema() -> None:
    """A bump with nothing to protect strands queued work behind a new Executor for nothing."""
    previous = load_snapshot(ORCHESTRATION_EVENT_EPOCH - 1)
    if previous is None:
        pytest.skip(f"Event Epoch {ORCHESTRATION_EVENT_EPOCH} is the first with a snapshot")
    assert previous != load_snapshot(ORCHESTRATION_EVENT_EPOCH), (
        f"Event Epochs {ORCHESTRATION_EVENT_EPOCH - 1} and {ORCHESTRATION_EVENT_EPOCH} "
        f"have identical snapshots: the bump protects nothing. Revert it."
    )
