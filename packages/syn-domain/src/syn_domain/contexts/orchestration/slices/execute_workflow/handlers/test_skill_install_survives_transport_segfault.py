"""A phase that declares several skills must survive the transport segfault (#1046).

The local `docker` client intermittently dies of SIGSEGV (exit -11) on any
`docker exec`. Each `skills add` is one exec, so without a retry a phase with
five skills failed five times as often as a phase with one, and multi-skill
phases looked broken. Only the local signal death is retried: a positive exit
is the installer refusing, and a -1 is a timeout or missing container.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import pytest

from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

module = importlib.import_module(
    "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.skill_install"
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

SEGFAULT = ExecutionResult(exit_code=-11, success=False, duration_ms=5.0)
OK = ExecutionResult(exit_code=0, success=True, duration_ms=5.0)
REFUSED = ExecutionResult(exit_code=1, success=False, duration_ms=5.0, stderr="bad skill")
TIMED_OUT = ExecutionResult(exit_code=-1, success=False, duration_ms=5.0, timed_out=True)

SKILLS = ("review", "architecture", "principles", "purpose-and-scope", "complexity")


def _workspace(*results: ExecutionResult) -> AsyncMock:
    workspace = AsyncMock()
    workspace.execute = AsyncMock(side_effect=list(results))
    return workspace


@pytest.fixture(autouse=True)
def _no_backoff():
    with patch.object(module.asyncio, "sleep", AsyncMock()):
        yield


async def test_five_skills_each_segfaulting_once_all_install() -> None:
    workspace = _workspace(*[r for _ in SKILLS for r in (SEGFAULT, OK)])

    for name in SKILLS:
        await module.install_skill(workspace, name, f"/workspace/.syn-skills/{name}", "claude-code")

    assert workspace.execute.await_count == 2 * len(SKILLS)
    installed = [c.args[0][2] for c in workspace.execute.await_args_list]
    assert installed == [f"/workspace/.syn-skills/{n}" for n in SKILLS for _ in (0, 1)]


async def test_persistent_segfault_still_fails_bounded() -> None:
    attempts = len(module._SKILL_INSTALL_RETRY_BACKOFF_SECONDS) + 1
    workspace = _workspace(*[SEGFAULT] * attempts)

    with pytest.raises(SkillInstallFailed, match="purpose-and-scope"):
        await module.install_skill(workspace, "purpose-and-scope", "/src", "claude-code")

    assert workspace.execute.await_count == attempts


@pytest.mark.parametrize("result", [REFUSED, TIMED_OUT], ids=["installer-refused", "timeout"])
async def test_non_signal_failures_fail_fast(result: ExecutionResult) -> None:
    workspace = _workspace(result, OK)

    with pytest.raises(SkillInstallFailed):
        await module.install_skill(workspace, "review", "/src", "claude-code")

    assert workspace.execute.await_count == 1
