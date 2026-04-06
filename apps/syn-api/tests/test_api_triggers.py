"""Tests for syn_api.routes.triggers — register, list, get, pause, resume, delete cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os

import pytest

from syn_api.types import Err, Ok

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage between tests."""
    import syn_api._wiring
    from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
        reset_trigger_store,
    )

    reset_trigger_store()
    syn_api._wiring._test_trigger_repo = None
    yield
    reset_trigger_store()
    syn_api._wiring._test_trigger_repo = None


@pytest.fixture(autouse=True)
async def _seed_test_workflows():
    """Seed the in-memory workflow store with workflow IDs used by trigger tests.

    Trigger registration validates that the referenced workflow exists (via
    InMemoryWorkflowRepository.exists), so we must create them first.
    """
    from syn_api._wiring import ensure_connected

    await ensure_connected()

    from syn_adapters.storage.in_memory import get_event_store

    store = get_event_store()
    for wf_id in ("wf-1", "wf-2", "wf-3", "ci-fix-workflow", "wf-abc"):
        store.append(
            aggregate_id=wf_id,
            aggregate_type="WorkflowTemplate",
            event_type="WorkflowTemplateCreated",
            event_data={
                "workflow_id": wf_id,
                "name": f"test-workflow-{wf_id}",
                "workflow_type": "custom",
                "classification": "simple",
                "repository_url": "https://github.com/test/repo",
                "repository_ref": "main",
                "phases": [
                    {
                        "phase_id": "phase-1",
                        "name": "phase1",
                        "order": 1,
                    }
                ],
            },
            version=1,
        )


async def test_register_trigger():
    """Register a trigger and get back an ID."""
    from syn_api.routes.triggers import register_trigger

    result = await register_trigger(
        name="ci-self-heal",
        event="check_run.completed",
        repository="syntropic137/my-project",
        workflow_id="ci-fix-workflow",
    )

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert len(result.value) > 0


async def test_register_trigger_invalid_input():
    """Register with missing required fields fails."""
    from syn_api.routes.triggers import register_trigger

    result = await register_trigger(
        name="",
        event="push",
        repository="owner/repo",
        workflow_id="wf-1",
    )

    assert isinstance(result, Err)


async def test_list_triggers_empty():
    """List triggers when none exist."""
    from syn_api.routes.triggers import list_triggers

    result = await list_triggers()

    assert isinstance(result, Ok)
    assert result.value == []


async def test_register_and_list_triggers():
    """Register a trigger then list it."""
    from syn_api.routes.triggers import list_triggers, register_trigger

    await register_trigger(
        name="test-trigger",
        event="push",
        repository="owner/repo",
        workflow_id="wf-1",
    )

    result = await list_triggers()
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    assert result.value[0].name == "test-trigger"
    assert result.value[0].event == "push"
    assert result.value[0].repository == "owner/repo"
    assert result.value[0].status == "active"


async def test_list_triggers_filter_by_repository():
    """Filter triggers by repository."""
    from syn_api.routes.triggers import list_triggers, register_trigger

    await register_trigger(name="t1", event="push", repository="owner/repo-a", workflow_id="wf-1")
    await register_trigger(name="t2", event="push", repository="owner/repo-b", workflow_id="wf-2")

    result = await list_triggers(repository="owner/repo-a")
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    assert result.value[0].name == "t1"


async def test_get_trigger():
    """Register a trigger then get its details."""
    from syn_api.routes.triggers import get_trigger, register_trigger

    reg_result = await register_trigger(
        name="detail-trigger",
        event="pull_request",
        repository="owner/repo",
        workflow_id="wf-1",
        conditions=[{"field": "action", "operator": "eq", "value": "opened"}],
        installation_id="inst-123",
        created_by="test-user",
    )
    assert isinstance(reg_result, Ok)
    trigger_id = reg_result.value

    result = await get_trigger(trigger_id)
    assert isinstance(result, Ok)
    assert result.value.trigger_id == trigger_id
    assert result.value.name == "detail-trigger"
    assert result.value.event == "pull_request"
    assert result.value.installation_id == "inst-123"
    assert result.value.created_by == "test-user"
    assert len(result.value.conditions) == 1


async def test_get_trigger_not_found():
    """Get a trigger that doesn't exist."""
    from syn_api.routes.triggers import get_trigger

    result = await get_trigger("nonexistent-id")
    assert isinstance(result, Err)


async def test_pause_trigger():
    """Pause an active trigger."""
    from syn_api.routes.triggers import get_trigger, pause_trigger, register_trigger

    reg_result = await register_trigger(
        name="pausable", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    result = await pause_trigger(trigger_id, reason="maintenance")
    assert isinstance(result, Ok)

    # Verify status changed
    detail = await get_trigger(trigger_id)
    assert isinstance(detail, Ok)
    assert detail.value.status == "paused"


async def test_pause_already_paused():
    """Pausing an already-paused trigger returns error with descriptive message."""
    from syn_api.routes.triggers import pause_trigger, register_trigger

    reg_result = await register_trigger(
        name="double-pause", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    await pause_trigger(trigger_id)
    result = await pause_trigger(trigger_id)
    assert isinstance(result, Err)
    assert result.error == "already_paused"
    assert "already paused" in result.message.lower()


async def test_pause_deleted_trigger():
    """Pausing a deleted trigger returns already-deleted error."""
    from syn_api.routes.triggers import delete_trigger, pause_trigger, register_trigger

    reg_result = await register_trigger(
        name="pause-deleted", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    await delete_trigger(trigger_id)
    result = await pause_trigger(trigger_id)
    assert isinstance(result, Err)
    assert result.error == "already_deleted"
    assert "deleted" in result.message.lower()


async def test_pause_not_found():
    """Pausing a nonexistent trigger returns not-found error."""
    from syn_api.routes.triggers import pause_trigger

    result = await pause_trigger("nonexistent-id")
    assert isinstance(result, Err)
    assert result.error == "not_found"
    assert "not found" in result.message.lower()


async def test_resume_trigger():
    """Resume a paused trigger."""
    from syn_api.routes.triggers import get_trigger, pause_trigger, register_trigger, resume_trigger

    reg_result = await register_trigger(
        name="resumable", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    await pause_trigger(trigger_id)
    result = await resume_trigger(trigger_id)
    assert isinstance(result, Ok)

    detail = await get_trigger(trigger_id)
    assert isinstance(detail, Ok)
    assert detail.value.status == "active"


async def test_delete_trigger():
    """Delete a trigger."""
    from syn_api.routes.triggers import delete_trigger, get_trigger, register_trigger

    reg_result = await register_trigger(
        name="deletable", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    result = await delete_trigger(trigger_id)
    assert isinstance(result, Ok)

    detail = await get_trigger(trigger_id)
    assert isinstance(detail, Ok)
    assert detail.value.status == "deleted"


async def test_resume_active_trigger():
    """Resuming an already-active trigger returns error with descriptive message."""
    from syn_api.routes.triggers import register_trigger, resume_trigger

    reg_result = await register_trigger(
        name="resume-active", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    result = await resume_trigger(trigger_id)
    assert isinstance(result, Err)
    assert result.error == "already_active"
    assert "not paused" in result.message.lower()


async def test_resume_deleted_trigger():
    """Resuming a deleted trigger returns already-deleted error."""
    from syn_api.routes.triggers import delete_trigger, register_trigger, resume_trigger

    reg_result = await register_trigger(
        name="resume-deleted", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    await delete_trigger(trigger_id)
    result = await resume_trigger(trigger_id)
    assert isinstance(result, Err)
    assert result.error == "already_deleted"
    assert "deleted" in result.message.lower()


async def test_resume_not_found():
    """Resuming a nonexistent trigger returns not-found error."""
    from syn_api.routes.triggers import resume_trigger

    result = await resume_trigger("nonexistent-id")
    assert isinstance(result, Err)
    assert result.error == "not_found"
    assert "not found" in result.message.lower()


async def test_delete_already_deleted():
    """Deleting an already-deleted trigger returns error with descriptive message."""
    from syn_api.routes.triggers import delete_trigger, register_trigger

    reg_result = await register_trigger(
        name="double-delete", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    await delete_trigger(trigger_id)
    result = await delete_trigger(trigger_id)
    assert isinstance(result, Err)
    assert result.error == "already_deleted"
    assert "already been deleted" in result.message.lower()


async def test_delete_not_found():
    """Deleting a nonexistent trigger returns not-found error."""
    from syn_api.routes.triggers import delete_trigger

    result = await delete_trigger("nonexistent-id")
    assert isinstance(result, Err)
    assert result.error == "not_found"
    assert "not found" in result.message.lower()


async def test_disable_triggers():
    """Disable all triggers for a repository."""
    from syn_api.routes.triggers import disable_triggers, list_triggers, register_trigger

    await register_trigger(name="t1", event="push", repository="owner/repo", workflow_id="wf-1")
    await register_trigger(
        name="t2", event="pull_request", repository="owner/repo", workflow_id="wf-2"
    )
    await register_trigger(name="t3", event="push", repository="other/repo", workflow_id="wf-3")

    result = await disable_triggers(repository="owner/repo")
    assert isinstance(result, Ok)
    assert result.value == 2

    # Verify only owner/repo triggers are paused
    all_triggers = await list_triggers()
    assert isinstance(all_triggers, Ok)
    for t in all_triggers.value:
        if t.repository == "owner/repo":
            assert t.status == "paused"
        else:
            assert t.status == "active"


async def test_full_lifecycle():
    """Register → list → get → pause → resume → delete cycle."""
    from syn_api.routes.triggers import (
        delete_trigger,
        get_trigger,
        list_triggers,
        pause_trigger,
        register_trigger,
        resume_trigger,
    )

    # Register
    reg = await register_trigger(
        name="lifecycle",
        event="push",
        repository="owner/repo",
        workflow_id="wf-1",
    )
    assert isinstance(reg, Ok)
    tid = reg.value

    # List
    lst = await list_triggers()
    assert isinstance(lst, Ok)
    assert len(lst.value) == 1

    # Get
    detail = await get_trigger(tid)
    assert isinstance(detail, Ok)
    assert detail.value.status == "active"

    # Pause
    assert isinstance(await pause_trigger(tid), Ok)
    detail = await get_trigger(tid)
    assert detail.value.status == "paused"

    # Resume
    assert isinstance(await resume_trigger(tid), Ok)
    detail = await get_trigger(tid)
    assert detail.value.status == "active"

    # Delete
    assert isinstance(await delete_trigger(tid), Ok)
    detail = await get_trigger(tid)
    assert detail.value.status == "deleted"
