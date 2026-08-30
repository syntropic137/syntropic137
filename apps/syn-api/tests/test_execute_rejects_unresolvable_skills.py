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


class TestItDoesNotRefuseWorkItShouldAccept:
    async def test_a_workflow_with_no_skills_never_touches_the_resolver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Most workflows declare none. Constructing the service for them would
        make every execution pay for a feature it does not use."""
        wf = _Workflow([_Phase("research"), _Phase("plan")])
        resolver = _Resolver()
        await _check(monkeypatch, wf, resolver)
        assert resolver.calls == 0

    async def test_resolvable_skills_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = _Workflow([_Phase("research", skills=("ref",))])
        resolver = _Resolver()
        await _check(monkeypatch, wf, resolver)
        assert resolver.calls == 1

    async def test_an_unavailable_RESOLVER_does_not_block_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-open on OUR infrastructure, fail-closed on THEIR input.

        A missing registration is a user error and must be reported. A resolver
        that cannot be constructed is our problem, and refusing to run any
        workflow because of it would turn a degraded subsystem into a total
        outage.
        """
        from syn_api.routes.executions import commands

        async def _boom() -> object:
            raise RuntimeError("resolver unavailable")

        import syn_api._wiring as wiring

        monkeypatch.setattr(wiring, "get_skill_resolution_service", _boom)
        wf = _Workflow([_Phase("research", skills=("ref",))])
        await commands._reject_unresolvable_skill_refs(wf)  # type: ignore[arg-type]
