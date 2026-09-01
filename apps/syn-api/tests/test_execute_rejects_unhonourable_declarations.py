"""A stored declaration we cannot honour is a 422, never a ghost execution (#1039).

The failure this prevents: the endpoint returns
``200 {"status": "started", "execution_id": "exec-..."}``, the BackgroundTask
then raises in ``_get_executable_phases`` BEFORE any execution stream is
created, and polling that id returns 404 forever. Nothing anywhere records that
the run was refused or why.

This is the same defect #998 fixed for unresolvable skill refs and ADR-068
fixed for removed providers, so it gets the same treatment in the same place.

Every shape here is reachable ONLY from a stored template. YAML authoring
already refuses all three, but a template stored before those rules rehydrates
straight from its historical ``WorkflowTemplateCreated`` event and never sees
the validator. Measured on the deployment: 11 phases across 4 workflows declare
the non-tool ``git``, and 2 codex phases declare tool policies.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

import pytest
from fastapi import HTTPException

from syn_shared.agents import AgentProvider

pytestmark = pytest.mark.unit


@dataclass
class _Phase:
    phase_id: str
    execution_type: str = "sequential"
    allowed_tools: list[str] = field(default_factory=list)
    provider: str | None = None


@dataclass
class _Workflow:
    phases: list[_Phase]


def _check(phases: list[_Phase]) -> None:
    from syn_api.routes.executions.commands import _check_phase_declarations

    _check_phase_declarations(_Workflow(phases))  # type: ignore[arg-type]


class TestTheseAreRefusedBeforeAnExecutionIdIsHandedOut:
    def test_an_unimplemented_execution_type(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _check([_Phase("plan", execution_type="parallel")])

        assert exc.value.status_code == 422
        assert "parallel" in str(exc.value.detail)
        assert "plan" in str(exc.value.detail)

    def test_human_in_loop_too_because_it_is_the_same_defect(self) -> None:
        """The dangerous half: its author believes a human gates the phase."""
        with pytest.raises(HTTPException) as exc:
            _check([_Phase("approve", execution_type="human_in_loop")])

        assert exc.value.status_code == 422

    def test_a_tool_name_outside_the_vocabulary(self) -> None:
        """`git` is not a tool on any harness. 11 installed phases declare it."""
        with pytest.raises(HTTPException) as exc:
            _check([_Phase("fix", allowed_tools=["bash", "git", "read"])])

        assert exc.value.status_code == 422
        assert "git" in str(exc.value.detail)

    def test_a_blank_tool_entry(self) -> None:
        """`[""]` would otherwise normalise to "declared nothing" and run
        completely unrestricted while reading as scoped."""
        with pytest.raises(HTTPException) as exc:
            _check([_Phase("fix", allowed_tools=[""])])

        assert exc.value.status_code == 422

    def test_codex_declaring_tools_it_cannot_honour(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _check(
                [
                    _Phase(
                        "delegate",
                        allowed_tools=["Read", "Grep"],
                        provider=AgentProvider.CODEX,
                    )
                ]
            )

        assert exc.value.status_code == 422
        assert "codex" in str(exc.value.detail).lower()

    def test_a_later_phase_is_checked_not_only_the_first(self) -> None:
        """Guessing "the first phase" is wrong whenever a later one is broken -
        the mistake the skill preflight above already documents."""
        with pytest.raises(HTTPException) as exc:
            _check([_Phase("ok"), _Phase("broken", allowed_tools=["git"])])

        assert "broken" in str(exc.value.detail)


class TestValidDeclarationsPassCleanly:
    def test_a_sequential_claude_phase_with_real_tools(self) -> None:
        _check([_Phase("research", allowed_tools=["Read", "Bash"])])

    def test_lowercase_is_still_forgiven(self) -> None:
        """Case was always unambiguous; only unknown names are refused."""
        _check([_Phase("research", allowed_tools=["read", "bash"])])

    def test_a_phase_declaring_nothing(self) -> None:
        _check([_Phase("research")])

    def test_codex_without_tools(self) -> None:
        _check([_Phase("review", provider=AgentProvider.CODEX)])


class TestTheROUTEActuallyCallsThePreflight:
    """Binds the route to the helper.

    Every test above drives `_check_phase_declarations` directly, and all of
    them would pass with the CALL SITE deleted from
    `_validate_execution_request` - proving the helper works while the endpoint
    carries on returning 200 and stranding the caller. That exact gap is
    recorded in test_execute_rejects_unresolvable_skills.py; repeating the
    helper-only pattern here would repeat the bug.
    """

    async def test_validate_execution_request_invokes_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.executions import commands

        called: list[object] = []

        async def _connected() -> None:
            return None

        async def _no_skill_check(_w: object) -> None:
            return None

        workflow = _Workflow([_Phase("research")])

        class _Repo:
            async def get_by_id(self, _id: str) -> object:
                return workflow

        monkeypatch.setattr(commands, "ensure_connected", _connected)
        monkeypatch.setattr(commands, "get_workflow_repo", lambda: _Repo())
        monkeypatch.setattr(commands, "_check_phase_providers", lambda _w: None)
        monkeypatch.setattr(commands, "_reject_unresolvable_skill_refs", _no_skill_check)
        monkeypatch.setattr(commands, "_check_phase_declarations", lambda w: called.append(w))

        with contextlib.suppress(Exception):
            # Later stages need more wiring than this test provides. The only
            # claim here is that the declaration preflight runs at all.
            await commands._validate_execution_request("wf-1", _StubRequest())  # type: ignore[arg-type]

        assert called, "the route did not invoke the declaration preflight"
        assert called[0] is workflow


@dataclass
class _StubRequest:
    inputs: dict[str, str] = field(default_factory=dict)
    repos: list[str] = field(default_factory=list)


class TestTheTriggerPathRefusesBeforeItAcknowledges:
    """A trigger must never report `dispatched` for a run that cannot happen.

    `WorkflowDispatchProjection` awaits `run_workflow()` and then writes
    `status="dispatched"`. `run_workflow()` used to only create an asyncio
    task, so a stored template carrying an unhonourable declaration produced: a
    trigger record saying dispatched, an execution id that resolves 404
    forever, and a swallowed exception in the task. The refusal now happens
    SYNCHRONOUSLY, before the task exists, so it reaches the projection's
    `dispatch_exception` path and the record is marked `failed` instead.

    This is the path that matters most in practice: CI Self-Healing and PR
    Review are trigger-driven, and both are among the four installed workflows
    measured to carry a declaration the platform will not honour.
    """

    async def test_run_workflow_raises_instead_of_scheduling_a_doomed_task(self) -> None:
        from syn_api._wiring import BackgroundWorkflowDispatcher
        from syn_domain.contexts.orchestration import UnsupportedExecutionTypeError

        handled: list[object] = []

        class _Handler:
            async def validate_stored_declarations(self, _wid: str) -> None:
                raise UnsupportedExecutionTypeError("parallel", phase_id="plan")

            async def handle(self, cmd: object) -> None:
                handled.append(cmd)

        dispatcher = BackgroundWorkflowDispatcher(_Handler())  # type: ignore[arg-type]

        with pytest.raises(UnsupportedExecutionTypeError):
            await dispatcher.run_workflow("wf-1", {}, "exec-1")

        # The projection writes `dispatched` only if run_workflow RETURNS, so
        # raising is what marks the record failed. And nothing was scheduled.
        assert not handled
        assert not dispatcher._tasks

    async def test_a_valid_template_still_dispatches(self) -> None:
        import asyncio

        from syn_api._wiring import BackgroundWorkflowDispatcher

        handled: list[object] = []

        class _Handler:
            async def validate_stored_declarations(self, _wid: str) -> None:
                return None

            async def handle(self, cmd: object) -> None:
                handled.append(cmd)

        dispatcher = BackgroundWorkflowDispatcher(_Handler())  # type: ignore[arg-type]
        await dispatcher.run_workflow("wf-1", {}, "exec-1")
        await asyncio.gather(*list(dispatcher._tasks), return_exceptions=True)

        assert handled, "a valid template must still reach the handler"
