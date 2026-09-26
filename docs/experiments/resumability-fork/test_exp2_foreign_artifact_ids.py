"""EXPERIMENT 2: can execution F reference execution P's artifact ids and have
the read paths serve them?

Smallest case: P's phase "plan" produced one artifact (projected exactly as the
coordinator would, via ArtifactListProjection.on_artifact_created). F is a fork
that names "plan" as completed and holds P's artifact id. Every read path a
fork would depend on is asked for it, using the REAL ArtifactCollector and
ArtifactQueryService. Nothing about fork exists yet; this measures today's code.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import ArtifactListProjection
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit
P, F, ART, BODY = "exec-parent00001", "exec-fork000001", "art-parent-plan", "# PLAN\nparent body"


class _Ws:
    def __init__(self) -> None:
        self.injected: list[tuple[str, bytes]] = []

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        self.injected.extend(files)


class _Repo:
    async def save(self, aggregate: object) -> None: ...


async def _world() -> tuple[InMemoryProjectionStore, ArtifactListProjection, ArtifactCollector]:
    store = InMemoryProjectionStore()
    proj = ArtifactListProjection(store)
    await proj.on_artifact_created({
        "artifact_id": ART, "workflow_id": "wf", "execution_id": P, "phase_id": "plan",
        "artifact_type": "markdown", "title": "plan.md", "content": BODY,
        "source_path": "deliverable.md", "is_primary_deliverable": True,
    })
    collector = ArtifactCollector(repository=_Repo(), content_storage=None,  # type: ignore[arg-type]
                                  query_service=ArtifactQueryService(proj))
    return store, proj, collector


async def _inject(collector: ArtifactCollector, execution_id: str) -> list[tuple[str, bytes]]:
    # Exactly what a fork's processor would pass today: completed ids seeded,
    # in-memory caches EMPTY (they are initialised empty on every run,
    # WorkflowExecutionProcessor.py:292-307), so the projection is the only source.
    ws = _Ws()
    await collector.inject_from_previous_phases_explicit(
        workspace=ws, completed_phase_ids=["plan"], phase_outputs={},
        execution_id=execution_id, phase_files={})
    return ws.injected


async def test_read_paths_for_a_foreign_artifact_id() -> None:
    store, proj, collector = await _world()
    aqs = ArtifactQueryService(proj)

    control = await _inject(collector, P)          # the owning execution
    hazard = await _inject(collector, F)           # the fork, same completed ids
    alias_f = await aqs.get_for_phase_injection(execution_id=F, completed_phase_ids=["plan"])
    by_id = await proj.get_by_id(ART)              # GET /artifacts/{id} path
    listed_f = await proj.query(execution_id=F)    # GET /artifacts?execution_id=F path

    # Execution detail: does it accept a foreign id on F's own stream?
    detail = WorkflowExecutionDetailProjection(store)
    await detail.on_workflow_execution_started({"execution_id": F, "workflow_id": "wf",
                                                "inputs": {}, "total_phases": 2})
    await detail.on_phase_completed({"execution_id": F, "phase_id": "plan", "artifact_id": ART,
                                     "input_tokens": 0, "output_tokens": 0})
    f_detail = await detail.get_by_id(F)

    print(f"\nEXP2 injection into P's next phase (control): {[p for p, _ in control]}")
    print(f"EXP2 injection into F's next phase (hazard):   {[p for p, _ in hazard]}")
    print(f"EXP2 prompt alias for F: {alias_f}")
    print(f"EXP2 get_by_id({ART}): execution_id={by_id.execution_id if by_id else None} "
          f"content_ok={bool(by_id and by_id.content == BODY)}")
    print(f"EXP2 list artifacts for F: {[a.id for a in listed_f]}")
    print(f"EXP2 F detail artifact_ids: {f_detail.artifact_ids if f_detail else None}")

    assert BODY.encode() in [b for _, b in control]  # the path works for the owner
    assert hazard == []                             # ...and silently gives F nothing
    assert alias_f == {}
    assert by_id is not None and by_id.content == BODY
    assert listed_f == []


async def test_same_fork_call_after_relinking_row_to_fork() -> None:
    """Mutation: rewrite the projection row's execution_id to F (what COPYING
    would amount to). If F now receives the file, the empty result above was
    caused by the execution filter and nothing else."""
    store, proj, collector = await _world()
    row = await store.get(ArtifactListProjection.PROJECTION_NAME, ART)
    row["execution_id"] = F
    await store.save(ArtifactListProjection.PROJECTION_NAME, ART, row)
    assert (await proj.get_by_id(ART)).execution_id == F  # mutation applied
    got = await _inject(collector, F)
    print(f"\nEXP2 mutation (row relinked to F): {[p for p, _ in got]}")
    assert BODY.encode() in [b for _, b in got]
