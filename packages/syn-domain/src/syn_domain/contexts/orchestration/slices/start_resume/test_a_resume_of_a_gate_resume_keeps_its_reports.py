"""A resume of a resume hands over the evidence the first resume filed (plan §A.7).

The parent stops inside an evidence gate after `implement`; its child settles
the gate's last step, filing a report and the manifest under its own
execution, and is interrupted in turn. The grandchild inherits `implement`
from the child, owned by the parent. Its files are asked of every execution
holding one, through the real artifact projection and query, so the reports
the child filed are not silently dropped while the parent's still resolve.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)
from syn_domain.contexts.orchestration._shared.evidence_contract import StepOutcome
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    InterruptExecutionCommand,
    SettleEvidenceStepCommand,
    StartEvidenceAttemptCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_resume_evidence_gate import (
    CHILD,
    NOW,
    PARENT,
    S,
    _child,
    _parent_inside_a_gate,
    _resume,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ResumeOrigin,  # noqa: TC001 - the helper's return annotation
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    inherited_outputs,
)

pytestmark = pytest.mark.unit

GRANDCHILD = "exec-gate-grandchild"

#: Every artifact in the lineage and the execution it was filed under.
FILED = (
    (PARENT, "art-implement"),
    (PARENT, "rep-0-json"),
    (PARENT, "rep-0-md"),
    (CHILD, "child-report"),
    (CHILD, "child-manifest"),
)


async def _projection() -> ArtifactListProjection:
    projection = ArtifactListProjection(store=InMemoryProjectionStore())
    for owner, artifact_id in FILED:
        await projection.on_artifact_created(
            {
                "artifact_id": artifact_id,
                "execution_id": owner,
                "phase_id": "implement",
                "content": f"content of {artifact_id}",
                "source_path": f"{artifact_id}.md",
                "artifact_type": "document",
                "created_at": NOW.isoformat(),
            }
        )
    return projection


def _grandchild_origin() -> ResumeOrigin:
    parent, gate_id = _parent_inside_a_gate(completed=True)
    _resume(parent)
    child_stream, _started = _child(parent)
    child = child_stream.load()
    child.start_evidence_attempt(
        StartEvidenceAttemptCommand(CHILD, gate_id, 1, "d-1", NOW, NOW + timedelta(hours=1))
    )
    child.settle_evidence_step(
        SettleEvidenceStepCommand(
            CHILD,
            gate_id,
            1,
            StepOutcome.PASSED,
            head_sha_evidenced=S,
            report_artifact_ids=["child-report"],
            manifest_artifact_id="child-manifest",
        )
    )
    child.interrupt_execution(InterruptExecutionCommand(execution_id=CHILD, phase_id="review"))
    child_stream.save(child)
    child = child_stream.load()
    child.resume_execution(
        ResumeExecutionCommand(execution_id=CHILD, resume_execution_id=GRANDCHILD)
    )
    child_stream.save(child)
    _grandchild, (started,) = _child(child_stream)
    assert isinstance(started, WorkflowExecutionStartedEvent)
    assert started.resumed_from is not None
    return started.resumed_from


class TestAResumeOfAGateResume:
    def test_each_report_is_asked_of_the_execution_that_filed_it(self) -> None:
        origin = _grandchild_origin()
        (implement,) = origin.inherited_phases

        assert origin.owner_of(implement) == PARENT
        assert origin.artifacts_by_owner(implement) == {
            PARENT: ["art-implement", "rep-0-json", "rep-0-md"],
            CHILD: ["child-report", "child-manifest"],
        }

    async def test_every_file_in_the_lineage_reaches_the_grandchild(self) -> None:
        origin = _grandchild_origin()

        cache = await inherited_outputs(ArtifactQueryService(await _projection()), origin)

        assert sorted(f.source_path for f in cache.files["implement"]) == sorted(
            f"{artifact_id}.md" for _owner, artifact_id in FILED
        )
        assert {f.content for f in cache.files["implement"]} == {
            f"content of {artifact_id}" for _owner, artifact_id in FILED
        }
