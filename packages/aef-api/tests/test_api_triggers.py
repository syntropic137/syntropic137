"""Tests for aef_api.v1.triggers — register, list, get, pause, resume, delete cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os

import pytest

from aef_api.types import Err, Ok

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage between tests."""
    import aef_api._wiring
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        reset_trigger_store,
    )

    reset_trigger_store()
    aef_api._wiring._test_trigger_repo = None
    yield
    reset_trigger_store()
    aef_api._wiring._test_trigger_repo = None


async def test_register_trigger():
    """Register a trigger and get back an ID."""
    from aef_api.v1.triggers import register_trigger

    result = await register_trigger(
        name="ci-self-heal",
        event="check_run.completed",
        repository="AgentParadise/my-project",
        workflow_id="ci-fix-workflow",
    )

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert len(result.value) > 0


async def test_register_trigger_invalid_input():
    """Register with missing required fields fails."""
    from aef_api.v1.triggers import register_trigger

    result = await register_trigger(
        name="",
        event="push",
        repository="owner/repo",
        workflow_id="wf-1",
    )

    assert isinstance(result, Err)


async def test_list_triggers_empty():
    """List triggers when none exist."""
    from aef_api.v1.triggers import list_triggers

    result = await list_triggers()

    assert isinstance(result, Ok)
    assert result.value == []


async def test_register_and_list_triggers():
    """Register a trigger then list it."""
    from aef_api.v1.triggers import list_triggers, register_trigger

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
    from aef_api.v1.triggers import list_triggers, register_trigger

    await register_trigger(name="t1", event="push", repository="owner/repo-a", workflow_id="wf-1")
    await register_trigger(name="t2", event="push", repository="owner/repo-b", workflow_id="wf-2")

    result = await list_triggers(repository="owner/repo-a")
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    assert result.value[0].name == "t1"


async def test_get_trigger():
    """Register a trigger then get its details."""
    from aef_api.v1.triggers import get_trigger, register_trigger

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
    from aef_api.v1.triggers import get_trigger

    result = await get_trigger("nonexistent-id")
    assert isinstance(result, Err)


async def test_pause_trigger():
    """Pause an active trigger."""
    from aef_api.v1.triggers import get_trigger, pause_trigger, register_trigger

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
    """Pausing an already-paused trigger returns error."""
    from aef_api.v1.triggers import pause_trigger, register_trigger

    reg_result = await register_trigger(
        name="double-pause", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    await pause_trigger(trigger_id)
    result = await pause_trigger(trigger_id)
    assert isinstance(result, Err)


async def test_resume_trigger():
    """Resume a paused trigger."""
    from aef_api.v1.triggers import get_trigger, pause_trigger, register_trigger, resume_trigger

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
    from aef_api.v1.triggers import delete_trigger, get_trigger, register_trigger

    reg_result = await register_trigger(
        name="deletable", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    result = await delete_trigger(trigger_id)
    assert isinstance(result, Ok)

    detail = await get_trigger(trigger_id)
    assert isinstance(detail, Ok)
    assert detail.value.status == "deleted"


async def test_delete_already_deleted():
    """Deleting an already-deleted trigger returns error."""
    from aef_api.v1.triggers import delete_trigger, register_trigger

    reg_result = await register_trigger(
        name="double-delete", event="push", repository="owner/repo", workflow_id="wf-1"
    )
    trigger_id = reg_result.value

    await delete_trigger(trigger_id)
    result = await delete_trigger(trigger_id)
    assert isinstance(result, Err)


async def test_disable_triggers():
    """Disable all triggers for a repository."""
    from aef_api.v1.triggers import disable_triggers, list_triggers, register_trigger

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
    from aef_api.v1.triggers import (
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
