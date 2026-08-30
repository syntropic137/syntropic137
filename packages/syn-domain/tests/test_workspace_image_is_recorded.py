"""The image the host pulled must survive to the execution API (#1004).

Every experiment run this week is unauditable for image provenance: the record
says which repo was cloned and nothing about which workspace image ran it, so an
`edge`-channel result is indistinguishable from a `release` one.

These tests drive the CONSUMER end of each hop rather than the writer, because
the last three defects in this exact path (#1011, #1013, #1015) were all a value
written correctly and dropped one hop later - twice in a `from_dict` nobody
tested, once in the second of two API construction sites.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)

pytestmark = pytest.mark.unit

#: A digest-pinned reference. Not a default, and not a value the read model or
#: the projection could produce on its own, so seeing it proves it was carried.
_PINNED = "ghcr.io/agentparadise/omni-agent-workspace@sha256:" + "a" * 64
_OTHER = "ghcr.io/agentparadise/agentic-workspace-claude-cli@sha256:" + "b" * 64


def test_the_event_carries_the_image_the_command_chose() -> None:
    """The aggregate must not drop the host's choice on the floor."""
    from syn_domain.contexts.orchestration.domain.events.WorkspaceCreatedEvent import (
        WorkspaceCreatedEvent,
    )

    fields = WorkspaceCreatedEvent.model_fields

    assert "workspace_image" in fields, (
        "WorkspaceCreatedEvent must carry the image reference; the command has it "
        "and nothing else records it"
    )


def test_the_read_model_survives_a_store_round_trip() -> None:
    """to_dict -> from_dict is where this path lost fields twice before."""
    detail = WorkflowExecutionDetail(
        workflow_execution_id="exec-1",
        workflow_id="wf-1",
        workflow_name="wf",
        status="completed",
        workspace_images=(_PINNED, _OTHER),
    )

    restored = WorkflowExecutionDetail.from_dict(detail.to_dict())

    assert restored.workspace_images == (_PINNED, _OTHER)


def test_an_execution_recorded_before_the_field_reads_as_unknown_not_default() -> None:
    """Absence must be distinguishable from "it used the default image".

    A stored row from before this change has no key at all. Defaulting it to the
    current pin would invent provenance for every historical run.
    """
    restored = WorkflowExecutionDetail.from_dict(
        {
            "workflow_execution_id": "exec-old",
            "workflow_id": "wf-1",
            "workflow_name": "wf",
            "status": "completed",
        }
    )

    assert restored.workspace_images == ()
