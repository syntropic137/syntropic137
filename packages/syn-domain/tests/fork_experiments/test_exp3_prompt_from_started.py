"""EXPERIMENT 3: is the original input prompt recoverable from
WorkflowExecutionStartedEvent alone?

Two meanings, both measured:
  (a) the TASK and inputs the operator dispatched ($ARGUMENTS, {{key}}), and
  (b) the RENDERED phase prompt the agent actually received.

The inputs are built by the real ExecuteWorkflowHandler._merge_inputs (template
defaults folded in, task folded under TASK_INPUT_KEY) and then mutated the way
WorkflowExecutionProcessor.run does before the start command (inputs["repos"],
:256-257). The event is written through a real event-store client and READ
BACK (memory, or gRPC->Rust->Postgres when EXP_GRPC_ADDR is set), so the JSON
round trip is part of what is measured. The prompt is rendered by the real
production builder, syn_api._wiring._build_workspace_prompt.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_api._wiring import _build_workspace_prompt
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    PhaseDefinition,
    PhaseInput,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    InputDeclaration,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)

pytestmark = pytest.mark.unit
TASK = "Fix issue #77: the widget leaks — keep the public API stable. Ünïcode ✓ " + "x" * 5000
REPO = "https://github.com/acme/widgets"


@dataclass
class _Template:
    input_declarations: list[InputDeclaration] = field(default_factory=list)


def _phase(prompt: str, static: str) -> ExecutablePhase:
    return ExecutablePhase(phase_id="implement", name="Implement", order=2,
                           prompt_template=prompt, inputs=[PhaseInput(name="style", value=static)])


V1 = _phase("[{{execution_id}}] Task: $ARGUMENTS\nRepo: {{repos}} ticket={{ticket}} style={{style}}\n"
            "Plan: {{plan}}", "terse")
# The template after an operator edit: same phase id, different words/default/static input.
V2 = _phase("[{{execution_id}}] Implement carefully. $ARGUMENTS\nRepos: {{repos}} ticket={{ticket}} "
            "style={{style}}\nPlan: {{plan}}", "verbose")


async def _client() -> object:
    addr = os.environ.get("EXP_GRPC_ADDR")
    if addr:
        from event_sourcing.client.grpc_client import GrpcEventStoreClient

        c = GrpcEventStoreClient(address=addr, tenant_id="exp")
        await c.connect()
        return c
    return MemoryEventStoreClient()


async def test_replay_started_event() -> None:
    template_v1 = _Template([InputDeclaration(name="ticket", default="T-1")])
    cmd = ExecuteWorkflowCommand(aggregate_id="wf-1", inputs={"extra": "e"}, task=TASK)
    inputs: dict[str, object] = dict(ExecuteWorkflowHandler._merge_inputs(cmd, template_v1))  # type: ignore[arg-type]
    if "repos" not in inputs:  # WorkflowExecutionProcessor.run:256-257, verbatim condition
        inputs["repos"] = REPO

    eid = f"exec-{uuid.uuid4().hex[:12]}"
    agg = WorkflowExecutionAggregate()
    agg._handle_command(StartExecutionCommand(
        execution_id=eid, workflow_id="wf-1", workflow_name="W", total_phases=2, inputs=inputs,
        phase_definitions=[PhaseDefinition(phase_id="plan", name="Plan", order=1),
                           PhaseDefinition(phase_id="implement", name="Implement", order=2)]))
    client = await _client()
    repo = EventStoreRepository(client, WorkflowExecutionAggregate, "WorkflowExecution")
    await repo.save_new(agg)

    # What the agent received, rendered at dispatch time from the live inputs.
    outputs = {"plan": "PLAN TEXT"}
    original = await _build_workspace_prompt(V1, eid, "wf-1", REPO, outputs, inputs)

    # --- replay: read the stream back, nothing else ---
    raw = await client.read_events(f"WorkflowExecution-{eid}")  # type: ignore[attr-defined]
    started = raw[0].event
    payload = started.model_dump(mode="json")
    replayed_inputs = payload["inputs"]
    reloaded = await repo.load(eid)
    agg_state_has_task = any(TASK in repr(v) for v in vars(reloaded).values())

    print(f"\nEXP3 client={type(client).__name__} event_class={type(started).__name__}")
    print(f"EXP3 event payload keys: {sorted(payload)}")
    print(f"EXP3 inputs keys recovered: {sorted(replayed_inputs)}")
    print(f"EXP3 task byte-identical: {replayed_inputs.get('task') == TASK}")
    print(f"EXP3 rehydrated aggregate retains task anywhere in its state: {agg_state_has_task}")

    # (b) re-render from the replayed event with each template the fork could use
    same_tpl = await _build_workspace_prompt(V1, eid, "wf-1", REPO, outputs, replayed_inputs)
    fork_id = f"exec-{uuid.uuid4().hex[:12]}"
    as_fork_v1 = await _build_workspace_prompt(V1, fork_id, "wf-1", REPO, outputs, replayed_inputs)
    as_fork_v2 = await _build_workspace_prompt(V2, fork_id, "wf-1", REPO, outputs, replayed_inputs)
    print(f"EXP3 re-render, template v1, parent id: identical={same_tpl == original}")
    print(f"EXP3 re-render, template v1, FORK id:   identical={as_fork_v1 == original}")
    print(f"EXP3 v1+fork id differs ONLY by the id: {as_fork_v1.replace(fork_id, eid) == original}")
    print(f"EXP3 re-render, template v2, FORK id:   identical={as_fork_v2 == original}")
    print(f"EXP3 prompt_template text in event: {V1.prompt_template in repr(payload)}; "
          f"static phase input 'terse' in event: {'terse' in repr(payload)}")

    assert replayed_inputs.get("task") == TASK
    assert same_tpl == original
    assert as_fork_v2 != original
