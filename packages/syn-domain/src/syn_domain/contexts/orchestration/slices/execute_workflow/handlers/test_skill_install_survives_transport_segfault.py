"""A phase that declares several skills must survive the transport segfault (#1046).

The local `docker` client intermittently dies of SIGSEGV (exit -11) on any
`docker exec`. Each `skills add` is one exec, so without a retry a phase with
five skills failed five times as often as a phase with one, and multi-skill
phases looked broken. The local signal death is retried: a positive exit
is the installer refusing, and a -1 without a timeout is a missing container.

A timeout is retried once (PC-126): under host load an install that would
finish is killed at its deadline. A second timeout is a transient, resumable
provision failure naming the step, not a broken skill.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import pytest

from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ProvisionStep,
    ProvisionStepTimeoutError,
    failure_account,
)
from syn_shared.settings import reset_settings
from syn_shared.upstream_failure import UpstreamFailureKind

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


@pytest.fixture
def install_timeout(monkeypatch: pytest.MonkeyPatch):
    """A configured timeout no default could produce, so reading it is proven."""
    monkeypatch.setenv("SKILL_INSTALL_TIMEOUT_SECONDS", "417")
    reset_settings()
    yield 417
    monkeypatch.delenv("SKILL_INSTALL_TIMEOUT_SECONDS")
    reset_settings()


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


async def test_installer_refusal_fails_fast() -> None:
    workspace = _workspace(REFUSED, OK)

    with pytest.raises(SkillInstallFailed):
        await module.install_skill(workspace, "review", "/src", "claude-code")

    assert workspace.execute.await_count == 1


async def test_one_timeout_is_retried_with_the_configured_timeout(install_timeout: int) -> None:
    workspace = _workspace(TIMED_OUT, OK)

    await module.install_skill(workspace, "review", "/src", "claude-code")

    assert workspace.execute.await_count == 2
    assert [c.kwargs["timeout_seconds"] for c in workspace.execute.await_args_list] == [
        install_timeout,
        install_timeout,
    ]


async def test_a_second_timeout_is_a_transient_provision_failure(install_timeout: int) -> None:
    workspace = _workspace(TIMED_OUT, TIMED_OUT, OK)

    with pytest.raises(ProvisionStepTimeoutError, match=r"skill_install.*'review'.*417s") as raised:
        await module.install_skill(workspace, "review", "/src", "claude-code")

    assert workspace.execute.await_count == 2
    assert raised.value.step is ProvisionStep.SKILL_INSTALL
    assert raised.value.attempts == 2
    # What the WorkflowFailed event records: resumable, not a broken skill.
    account = failure_account(raised.value)
    assert account.upstream is UpstreamFailureKind.UNAVAILABLE
    assert account.upstream.is_transient


async def test_timeouts_are_counted_across_segfault_retries() -> None:
    workspace = _workspace(TIMED_OUT, SEGFAULT, TIMED_OUT, OK)

    with pytest.raises(ProvisionStepTimeoutError):
        await module.install_skill(workspace, "review", "/src", "claude-code")

    assert workspace.execute.await_count == 3
