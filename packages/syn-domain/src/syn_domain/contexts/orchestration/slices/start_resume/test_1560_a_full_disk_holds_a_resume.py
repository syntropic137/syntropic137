"""A resume refused for a full disk is held, not spent (#1560).

A start that fails for an infrastructure reason counts an attempt and settles
`failed` at MAX_START_ATTEMPTS. A full volume is not that: it is the admission
gate refusing, and it clears when an operator frees space. Counted, it would
fail an admitted resume because the disk stayed full for a few passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts._shared.disk_space import (
    DiskCheck,
    DiskState,
    DiskUsage,
    InsufficientDiskSpaceError,
)
from syn_domain.contexts.orchestration.slices.start_resume.ResumeStartProcessManager import (
    ResumeStartProcessManager,
)
from syn_domain.contexts.orchestration.slices.start_resume.value_objects import (
    MAX_START_ATTEMPTS,
    OWED_STATUSES,
    ResumeStartRecord,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.start_resume.ResumeStartProcessManager import (
        StartFailureReporter,
    )

pytestmark = pytest.mark.unit

PARENT = "exec-parent"

_FULL = InsufficientDiskSpaceError(
    DiskCheck(
        path="/workspaces",
        state=DiskState.CRITICAL,
        usage=DiskUsage(free_bytes=3, total_bytes=100),
        degraded_below_percent=10.0,
        refuse_admission_below_percent=5.0,
    )
)


@dataclass
class _RefusingStarter:
    raising: Exception

    async def start_resume(
        self, parent_execution_id: str, *, on_failure: StartFailureReporter
    ) -> None:
        del parent_execution_id, on_failure
        raise self.raising


async def _start_once(attempts: int) -> ResumeStartRecord:
    store = InMemoryProjectionStore()
    manager = ResumeStartProcessManager(resume_starter=_RefusingStarter(_FULL), store=store)
    record = ResumeStartRecord(
        parent_execution_id=PARENT, recorded_at=datetime.now(UTC), attempts=attempts
    )
    await manager._save(record)
    await manager._start(record)
    stored = await store.get(ResumeStartProcessManager.PROJECTION_NAME, PARENT)
    assert stored is not None, "the refusal recorded nothing"
    return ResumeStartRecord.model_validate(stored)


async def test_a_full_disk_holds_the_resume_without_spending_an_attempt() -> None:
    saved = await _start_once(attempts=0)
    assert saved.status == "paused"
    assert saved.attempts == 0
    assert saved.status in OWED_STATUSES


async def test_a_full_disk_on_the_last_attempt_still_does_not_fail_it() -> None:
    saved = await _start_once(attempts=MAX_START_ATTEMPTS - 1)
    assert saved.status == "paused"
