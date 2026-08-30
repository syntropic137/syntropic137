"""An unusable skill ref must be a 422, not a 200 that leads nowhere (#998).

Observed on the self-host: a workflow declaring nine unregistered skills got

    POST /workflows/{id}/execute   -> 200 {"status": "started"}
    GET  /executions/exec-0c4d...  -> 404, permanently

The platform knew exactly what was wrong - `SkillNotRegistered` names the skill,
its source, its pinned version, and two remedies - and all of it went to a log
file while the API reported success.

Skill resolution ran inside the BackgroundTask, after the 200 and BEFORE the
execution aggregate was first persisted, so the failure was unattributable by
construction: there was no execution row to mark failed.

For an orchestration platform this is worse than a generic failure. A 500 tells
a caller to look; a 200 tells it to wait. Every trigger, cron job and agent
built on this API would wait forever.
"""

from __future__ import annotations

import contextlib

import pytest
from fastapi import HTTPException

from syn_domain.contexts.orchestration import SkillInvalidName, SkillNotRegistered

pytestmark = pytest.mark.unit

_SOURCE = "https://github.com/syntropic137/software-leverage-points"
_VERSION = "1348146ae5fd1659f2022b3c2bef0218292348d4"


class _Phase:
    def __init__(self, phase_id: str, skills: tuple[object, ...] = ()) -> None:
        self.phase_id = phase_id
        self.skills = skills


class _Workflow:
    def __init__(self, phases: list[_Phase]) -> None:
        self.phases = phases
        self.skills = ()


class _Resolver:
    """Stands in for SkillResolutionService."""

    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.calls = 0

    async def resolve_for_phase(self, workflow_refs: object, phase_refs: object) -> tuple[()]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return ()


async def _check(monkeypatch: pytest.MonkeyPatch, workflow: _Workflow, resolver: object) -> None:
    """Run the boundary check with the resolver swapped out."""
    from syn_api.routes.executions import commands

    async def _get_service() -> object:
        return resolver

    import syn_api._wiring as wiring

    monkeypatch.setattr(wiring, "get_skill_resolution_service", _get_service)
    await commands._reject_unresolvable_skill_refs(workflow)  # type: ignore[arg-type]


class TestAnUnresolvableRefIsRejectedAtTheBoundary:
    async def test_an_unregistered_skill_raises_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """THE reported bug. Before this, the same input returned 200."""
        wf = _Workflow([_Phase("research", skills=("ref",))])
        resolver = _Resolver(SkillNotRegistered(_SOURCE, _VERSION, "architecture"))

        with pytest.raises(HTTPException) as exc:
            await _check(monkeypatch, wf, resolver)

        assert exc.value.status_code == 422

    async def test_the_response_names_the_skill_and_how_to_fix_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exception already carries the best description of the problem.

        A 422 whose body says 'invalid request' would be almost as useless as
        the 200 it replaces - the caller still could not act on it.
        """
        wf = _Workflow([_Phase("research", skills=("ref",))])
        resolver = _Resolver(SkillNotRegistered(_SOURCE, _VERSION, "architecture"))

        with pytest.raises(HTTPException) as exc:
            await _check(monkeypatch, wf, resolver)

        detail = str(exc.value.detail)
        assert "architecture" in detail, "the skill name must survive to the caller"
        assert _SOURCE in detail, "the source must survive"
        assert _VERSION in detail, "the pinned version must survive"
        assert "syn skill add" in detail, "the remedy must survive"
        assert "research" in detail, "the caller must know WHICH phase"

    async def test_any_skill_error_is_rejected_not_just_the_unregistered_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Catching only SkillNotRegistered would leave every sibling failure
        on the silent path - an invalid name would still 200-then-404.

        Uses a DIFFERENT SkillError subclass on purpose: the production code
        catches the base class, and a test that only ever raises the subclass
        named in the bug report would pass against a narrower catch.
        """
        wf = _Workflow([_Phase("plan", skills=("ref",))])
        resolver = _Resolver(SkillInvalidName("../etc/passwd", "path traversal in the skill name"))

        with pytest.raises(HTTPException) as exc:
            await _check(monkeypatch, wf, resolver)
        assert exc.value.status_code == 422


class TestWorkflowScopedSkillsAreValidatedToo:
    """A codex review found the first version validated PHASE refs only.

    Production resolves both scopes together
    (`ExecuteWorkflowHandler._resolve_phase_skills`), so a workflow whose only
    unregistered skill was WORKFLOW-scoped still returned 200 and then 404 -
    the exact bug, still reachable through a different door.
    """

    async def test_an_unregistered_WORKFLOW_scoped_skill_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wf = _Workflow([_Phase("research")])  # NO phase-level skills
        wf.skills = ("workflow-ref",)
        resolver = _Resolver(SkillNotRegistered(_SOURCE, _VERSION, "architecture"))

        with pytest.raises(HTTPException) as exc:
            await _check(monkeypatch, wf, resolver)
        assert exc.value.status_code == 422
        assert "architecture" in str(exc.value.detail)

    async def test_workflow_refs_reach_the_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Asserting the ARGUMENT, not just that a call happened: passing
        `()` for the workflow scope is exactly the bug being fixed."""
        seen: list[tuple[object, object]] = []

        class _Recording(_Resolver):
            async def resolve_for_phase(self, workflow_refs, phase_refs):  # type: ignore[no-untyped-def]
                seen.append((workflow_refs, phase_refs))
                return ()

        wf = _Workflow([_Phase("research", skills=("phase-ref",))])
        wf.skills = ("workflow-ref",)
        await _check(monkeypatch, wf, _Recording())

        assert seen, "the resolver was never called"
        workflow_refs, phase_refs = seen[0]
        assert workflow_refs == ("workflow-ref",), f"workflow scope dropped: {workflow_refs}"
        assert phase_refs == ("phase-ref",)


class TestItDoesNotRefuseWorkItShouldAccept:
    async def test_a_workflow_with_no_skills_never_CONSTRUCTS_the_resolver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spies the FACTORY, not `resolve_for_phase`.

        A codex review caught the earlier version counting resolve calls: it
        passed even with the early return deleted, because a resolver that is
        constructed and then handed no refs still records zero calls. The claim
        is that we never build the service at all, so the factory is what must
        be observed.
        """
        import syn_api._wiring as wiring
        from syn_api.routes.executions import commands

        built = 0

        async def _factory() -> object:
            nonlocal built
            built += 1
            return _Resolver()

        monkeypatch.setattr(wiring, "get_skill_resolution_service", _factory)
        wf = _Workflow([_Phase("research"), _Phase("plan")])
        await commands._reject_unresolvable_skill_refs(wf)  # type: ignore[arg-type]
        assert built == 0, "the resolver was constructed for a workflow with no skills"

    async def test_resolvable_skills_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = _Workflow([_Phase("research", skills=("ref",))])
        resolver = _Resolver()
        await _check(monkeypatch, wf, resolver)
        assert resolver.calls == 1

    async def test_an_unavailable_resolver_is_a_503_not_a_silent_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAILS CLOSED, reversing the first version of this fix.

        I originally skipped the preflight when the resolver could not be
        built, reasoning that a degraded subsystem should not block all work. A
        codex review showed that is wrong HERE: the background handler
        constructs the SAME resolver moments later, before persistence, so
        skipping just relocates the failure back into the window this exists to
        close - recreating the exact false success. Nothing retries in between,
        so a 200 would not be truthful.

        503, not 422: the caller did nothing wrong and should retry.
        """
        from syn_api.routes.executions import commands

        async def _boom() -> object:
            raise RuntimeError("resolver unavailable")

        import syn_api._wiring as wiring

        monkeypatch.setattr(wiring, "get_skill_resolution_service", _boom)
        wf = _Workflow([_Phase("research", skills=("ref",))])
        with pytest.raises(HTTPException) as exc:
            await commands._reject_unresolvable_skill_refs(wf)  # type: ignore[arg-type]
        assert exc.value.status_code == 503


class _StubRepo:
    def __init__(self, workflow: object) -> None:
        self._workflow = workflow

    async def get_by_id(self, _workflow_id: str) -> object:
        return self._workflow


class _StubRequest:
    """Minimal stand-in for ExecuteWorkflowRequest."""

    def __init__(self) -> None:
        self.inputs: dict[str, str] = {}
        self.task: str | None = "t"
        self.repos: list[str] = []
        self.provider = "claude"


class TestTheROUTEActuallyCallsThePreflight:
    """The finding that mattered most in review.

    Every other test here drives `_reject_unresolvable_skill_refs` directly, and
    ALL of them passed with the CALL SITE deleted from
    `_validate_execution_request`. They proved the helper worked while the
    endpoint carried on returning 200. Testing a helper is not testing a fix.

    This binds the route to the helper.
    """

    async def test_the_validator_invokes_the_preflight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting the call from `_validate_execution_request` fails here."""
        from syn_api.routes.executions import commands

        called: list[object] = []

        async def _spy(workflow: object) -> None:
            called.append(workflow)

        async def _connected() -> None:
            return None

        workflow = _Workflow([_Phase("research", skills=("ref",))])
        monkeypatch.setattr(commands, "_reject_unresolvable_skill_refs", _spy)
        monkeypatch.setattr(commands, "ensure_connected", _connected)
        monkeypatch.setattr(commands, "get_workflow_repo", lambda: _StubRepo(workflow))
        monkeypatch.setattr(commands, "_check_phase_providers", lambda _w: None)

        with contextlib.suppress(Exception):
            # Later stages need more wiring than this test provides. The only
            # claim here is that the preflight runs, and runs FIRST.
            await commands._validate_execution_request("wf-1", _StubRequest())  # type: ignore[arg-type]

        assert called, "the route did not invoke the skill preflight"
        assert called[0] is workflow, "the preflight was handed the wrong workflow"
