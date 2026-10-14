"""The default path times the start after settling cancelled work, as before #1310 1.3.

Settling owed cancelled work can take as long as the store does. Main read the
clock after it; the start-only split moved the read ahead of it, so every
default-path result reported a start earlier by however long settlement took.
The clock here only moves inside `settle`, so the order is the whole answer.
"""

from __future__ import annotations

import importlib
import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_1310_start_only_admission import (
    _World,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

# The package re-exports the class under the module's own name.
processor_module = importlib.import_module(
    "syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor"
)

_BEFORE = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
_SETTLEMENT = timedelta(minutes=5)


class _Clock:
    now_at = _BEFORE

    @classmethod
    def now(cls, tz: object = None) -> datetime:  # noqa: ARG003 - stands in for datetime.now(UTC)
        return cls.now_at


async def test_the_default_path_reads_the_clock_after_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World()
    await world.install()
    processor = world.processor(queued=False)
    monkeypatch.setattr(_Clock, "now_at", _BEFORE)
    monkeypatch.setattr(processor_module, "datetime", _Clock)

    async def slow_settle() -> int:
        _Clock.now_at = _BEFORE + _SETTLEMENT
        return 0

    monkeypatch.setattr(processor._cancelled_work, "settle", slow_settle)

    result = await ExecuteWorkflowHandler(
        processor=processor, workflow_repository=world.templates
    ).handle(
        ExecuteWorkflowCommand(
            aggregate_id=world.definition.id,
            execution_id="exec-timed",
            repos=[RepositoryRef.from_slug("acme/widgets")],
            inputs={"task": "fix it"},
        )
    )

    assert result.status != "admitted"
    assert result.started_at == _BEFORE + _SETTLEMENT
