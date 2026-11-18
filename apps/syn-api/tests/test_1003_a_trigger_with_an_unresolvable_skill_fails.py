"""#1003: a trigger whose workflow's skill cannot resolve fails with the resolver's message.

It used to be accepted, handed to a background task, and fail in there before
its execution existed: the record ended `failed` / `start_exception` (#1707),
and the message naming the skill, its source and the fix reached only a log.

These run the REAL dispatcher, the REAL projection and the REAL shared skill
preflight `POST /execute` also runs, as production wires them. Only the
workflow repository, the skill resolver and the handler are doubles.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.execution_budget import ExecutionBudget
from syn_api.services.skill_preflight import require_resolvable_skills_for
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)
from syn_domain.contexts.orchestration import SkillNotRegistered

pytestmark = pytest.mark.unit

_PATIENCE = 5.0
_TRIGGERED = "exec-trigger-1003"
_SOURCE = "https://github.com/acme/skills"
_VERSION = "v1"


class _Ref:
    def __init__(self, skill_name: str) -> None:
        self.source_url = _SOURCE
        self.version = _VERSION
        self.skill_name = skill_name


class _Phase:
    def __init__(self, phase_id: str, skill_name: str) -> None:
        self.phase_id = phase_id
        self.skills = (_Ref(skill_name),)


class _Workflow:
    def __init__(self, skill_name: str) -> None:
        self.phases = [_Phase("review", skill_name)]
        self.skills = ()


class _Workflows:
    def __init__(self, workflow: _Workflow) -> None:
        self._workflow = workflow

    async def get_by_id(self, _workflow_id: str) -> _Workflow:
        return self._workflow


class _Resolver:
    """Resolves only the skills that are registered, as the lock projection does."""

    async def resolve_for_phase(
        self, _workflow_refs: object, phase_refs: tuple[_Ref, ...]
    ) -> tuple[()]:
        for ref in phase_refs:
            if ref.skill_name != "registered":
                raise SkillNotRegistered(ref.source_url, ref.version, ref.skill_name)
        return ()


class _Handler:
    """The execution service's entry point; counts what it was asked to run."""

    def __init__(self) -> None:
        self.handled = 0

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(self, _command: object, *, admitted: object = None) -> None:
        del admitted
        self.handled += 1


async def _a_trigger_fires(
    monkeypatch: pytest.MonkeyPatch, skill_name: str
) -> tuple[_Handler, BackgroundWorkflowDispatcher, InMemoryProjectionStore, int]:
    import syn_adapters.storage as storage
    import syn_api._wiring as wiring

    async def _resolver() -> _Resolver:
        return _Resolver()

    monkeypatch.setattr(
        storage, "get_workflow_repository", lambda: _Workflows(_Workflow(skill_name))
    )
    monkeypatch.setattr(wiring, "get_skill_resolution_service", _resolver)

    handler = _Handler()
    dispatcher = BackgroundWorkflowDispatcher(
        handler,  # type: ignore[arg-type]
        maintenance=AdmissionGate(InMemoryMaintenanceAdapter()),
        budget=ExecutionBudget(1),
        skill_preflight=require_resolvable_skills_for,
    )
    store = InMemoryProjectionStore()
    projection = WorkflowDispatchProjection(execution_service=dispatcher, store=store)  # type: ignore[arg-type]
    event = TriggerFiredEvent(
        trigger_id="trg-1003",
        execution_id=_TRIGGERED,
        workflow_id="wf",
        workflow_inputs={},
        github_event_type="check_run.completed",
    )
    envelope = EventEnvelope(
        event=event,
        metadata=EventMetadata(
            event_type=TriggerFiredEvent.event_type,
            aggregate_id="trg-1003",
            aggregate_type="TriggerRule",
            aggregate_nonce=1,
            global_nonce=1,
        ),
    )
    await projection.handle_event(envelope, MemoryCheckpointStore())
    processed = await projection.process_pending()
    async with asyncio.timeout(_PATIENCE):
        while dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
            await asyncio.gather(*dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]
            await asyncio.sleep(0)
    return handler, dispatcher, store, processed


async def _status(store: InMemoryProjectionStore) -> tuple[str, str]:
    found = await store.get(WorkflowDispatchProjection.PROJECTION_NAME, _TRIGGERED)
    assert found is not None, "the trigger produced no dispatch record at all"
    return str(found.get("status")), str(found.get("status_reason"))


class TestATriggerWhoseSkillCannotResolve:
    async def test_fails_with_the_resolvers_message_and_starts_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler, dispatcher, store, processed = await _a_trigger_fires(monkeypatch, "missing-skill")
        try:
            status, reason = await _status(store)
            assert status == "failed"
            assert "phase 'review'" in reason
            assert "'missing-skill'" in reason, f"the reason does not name the skill: {reason!r}"
            assert f"{_SOURCE}@{_VERSION}" in reason
            assert "syn skill add" in reason, "the reason lost the resolver's remedy"
            assert handler.handled == 0, "an execution was started for an unstartable workflow"
            assert processed == 0, "a refused trigger was counted as dispatched"
        finally:
            await dispatcher.shutdown()


class TestATriggerWhoseSkillResolves:
    async def test_still_dispatches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler, dispatcher, store, processed = await _a_trigger_fires(monkeypatch, "registered")
        try:
            assert processed == 1
            assert handler.handled == 1
            assert (await _status(store))[0] == "dispatched"
        finally:
            await dispatcher.shutdown()
