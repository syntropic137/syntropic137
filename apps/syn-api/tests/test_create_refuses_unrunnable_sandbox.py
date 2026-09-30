"""The API create path refuses a sandbox level the workspace cannot run (#1434).

Checked before the template is persisted: the create path turns a ValueError
into INVALID_INPUT, so the caller gets an error instead of a 201 for a phase
that would die on its first command.
"""

from __future__ import annotations

import pytest

from syn_api.routes.workflows.commands import _build_phase_defs
from syn_shared.agents import UnrunnablePhaseSandboxError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("sandbox", ["read-only", "workspace-write"])
@pytest.mark.parametrize("spelling", ["flat", "agent"])
def test_create_refuses_an_unrunnable_level(sandbox: str, spelling: str) -> None:
    base = {"phase_id": "review", "name": "Review", "order": 1}
    phase = (
        {**base, "sandbox": sandbox}
        if spelling == "flat"
        else {**base, "agent": {"provider": "codex", "sandbox": sandbox}}
    )
    with pytest.raises(UnrunnablePhaseSandboxError, match="review"):
        _build_phase_defs([phase])  # type: ignore[list-item]


@pytest.mark.parametrize("declared", [None, "full-access"])
def test_create_accepts_the_runnable_level(declared: str | None) -> None:
    base = {"phase_id": "p", "name": "P", "order": 1}
    phase = {**base, "sandbox": declared} if declared else base
    (built,) = _build_phase_defs([phase])  # type: ignore[list-item]
    assert built.sandbox == "full-access"


@pytest.mark.parametrize("sandbox", ["read-only", "workspace-write"])
async def test_create_workflow_returns_invalid_input_and_persists_nothing(
    sandbox: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal reaches the caller as INVALID_INPUT, not an escaped 500.

    Building the phases used to happen before the error handling, so the
    ValueError escaped. Nothing may be stored: the event store is never
    touched.
    """
    from syn_api.routes.workflows import commands
    from syn_api.types import Err, WorkflowError

    async def _must_not_connect() -> None:
        pytest.fail("a refused workflow reached the event store")

    monkeypatch.setattr(commands, "ensure_connected", _must_not_connect)
    result = await commands.create_workflow(
        name="refused",
        phases=[{"phase_id": "review", "name": "Review", "order": 1, "sandbox": sandbox}],
    )
    assert isinstance(result, Err)
    assert result.error == WorkflowError.INVALID_INPUT
    assert "#1434" in (result.message or "")
