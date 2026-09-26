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
