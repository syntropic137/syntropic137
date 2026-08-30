"""The trigger list must report the resolved created_at, not the model default.

Found by the codex review of #955: `list_triggers()` resolves `created_at`, and
`list_triggers_endpoint()` rebuilt `TriggerSummary` without it, so the model's
`None` default answered instead. Identical mechanism to the workflow list bug,
one file over -- a manual DTO rebuild that silently drops a field.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.routes.triggers.queries import list_triggers_endpoint
from syn_api.types import Ok

pytestmark = pytest.mark.unit


@dataclass
class _T:
    trigger_id: str
    name: str
    event: str
    repository: str
    workflow_id: str
    workflow_name: str
    status: str
    fire_count: int
    created_at: str | None


async def _list(triggers: list[_T]):
    with patch(
        "syn_api.routes.triggers.queries.list_triggers",
        new=AsyncMock(return_value=Ok(triggers)),
    ):
        return await list_triggers_endpoint(repository=None, status=None)


async def test_created_at_survives_the_response_rebuild() -> None:
    resp = await _list(
        [
            _T(
                trigger_id="trg-1",
                name="ci-fix",
                event="check_run",
                repository="org/repo",
                workflow_id="wf-1",
                workflow_name="CI Fix",
                status="active",
                fire_count=3,
                created_at="2026-08-28T00:00:00Z",
            )
        ]
    )
    # Pydantic coerces the ISO string to a datetime; assert the instant, not the spelling.
    assert resp.triggers[0].created_at is not None
    assert resp.triggers[0].created_at.isoformat().startswith("2026-08-28T00:00:00")


async def test_a_genuinely_absent_created_at_is_still_none() -> None:
    """The fix must pass the value through, not fabricate one."""
    resp = await _list(
        [
            _T(
                trigger_id="trg-2",
                name="x",
                event="push",
                repository="org/repo",
                workflow_id="wf-2",
                workflow_name="X",
                status="active",
                fire_count=0,
                created_at=None,
            )
        ]
    )
    assert resp.triggers[0].created_at is None
