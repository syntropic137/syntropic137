"""End-to-end integration tests for the trigger system.

Tests the full flow: register trigger -> webhook arrives -> trigger fires.
"""

from __future__ import annotations

import pytest

from aef_domain.contexts.github._shared.trigger_presets import create_preset_command
from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
    PauseTriggerCommand,
)
from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from aef_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
)
from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
    ManageTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
    InMemoryTriggerStore,
)


def _ci_failure_payload(
    repo: str = "AgentParadise/my-project",
    pr_number: int = 42,
    conclusion: str = "failure",
    sender: str = "human-user",
    delivery_id: str = "del-001",
) -> dict:
    """Create a sample check_run.completed webhook payload."""
    return {
        "action": "completed",
        "sender": {"login": sender},
        "repository": {"full_name": repo},
        "installation": {"id": 12345},
        "check_run": {
            "name": "lint",
            "conclusion": conclusion,
            "output": {
                "title": "Lint failed",
                "summary": "2 errors found",
            },
            "html_url": f"https://github.com/{repo}/runs/123",
            "pull_requests": [
                {"number": pr_number, "head": {"ref": "feat/my-feature"}},
            ],
        },
        "_delivery_id": delivery_id,
    }


def _review_submitted_payload(
    repo: str = "AgentParadise/my-project",
    pr_number: int = 42,
    review_state: str = "changes_requested",
    reviewer: str = "reviewer-user",
    delivery_id: str = "del-002",
) -> dict:
    """Create a sample pull_request_review.submitted webhook payload."""
    return {
        "action": "submitted",
        "sender": {"login": reviewer},
        "repository": {"full_name": repo},
        "installation": {"id": 12345},
        "review": {
            "state": review_state,
            "body": "Please fix the error handling",
            "user": {"login": reviewer},
            "html_url": f"https://github.com/{repo}/pull/{pr_number}#pullrequestreview-1",
        },
        "pull_request": {
            "number": pr_number,
            "draft": False,
            "head": {"ref": "feat/my-feature"},
        },
        "_delivery_id": delivery_id,
    }


@pytest.mark.integration
class TestE2ERegisterAndFire:
    """E2E: Register trigger -> Send webhook -> Verify workflow dispatched."""

    @pytest.mark.asyncio
    async def test_register_trigger_then_webhook_fires(self) -> None:
        """Full flow: register CI self-heal, send failure webhook, verify dispatch."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        # Register a CI self-healing trigger
        cmd = RegisterTriggerCommand(
            name="ci-self-heal",
            event="check_run.completed",
            conditions=(
                {"field": "check_run.conclusion", "operator": "eq", "value": "failure"},
                {"field": "check_run.pull_requests", "operator": "not_empty"},
            ),
            repository="AgentParadise/my-project",
            installation_id="inst-123",
            workflow_id="ci-fix-workflow",
        )
        aggregate = await reg_handler.handle(cmd)
        trigger_id = aggregate.trigger_id

        # Simulate webhook
        eval_handler = EvaluateWebhookHandler(store=store)
        payload = _ci_failure_payload()

        results = await eval_handler.evaluate(
            event="check_run.completed",
            repository="AgentParadise/my-project",
            installation_id="inst-123",
            payload=payload,
        )

        # Verify: one trigger fired
        assert len(results) == 1
        assert results[0].trigger_id == trigger_id
        assert results[0].execution_id.startswith("exec-")

        # Verify: fire count incremented
        stored = await store.get(trigger_id)
        assert stored is not None
        assert stored.fire_count == 1


@pytest.mark.integration
class TestE2ESafetyGuards:
    """E2E: Safety guards prevent infinite loops and duplicates."""

    @pytest.mark.asyncio
    async def test_bot_sender_prevented(self) -> None:
        """Verify that bot senders don't trigger workflows."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix",
        )
        await reg_handler.handle(cmd)

        eval_handler = EvaluateWebhookHandler(store=store)
        payload = _ci_failure_payload(repo="org/repo", sender="aef-engineer-beta[bot]")

        results = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_max_attempts_prevents_infinite_loop(self) -> None:
        """Verify that max attempts prevents infinite retry loops."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix",
            config=(("max_attempts", 2), ("cooldown_seconds", 0)),
        )
        await reg_handler.handle(cmd)

        eval_handler = EvaluateWebhookHandler(store=store)

        # Fire 1 - should succeed
        r1 = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_ci_failure_payload(repo="org/repo", delivery_id="del-1"),
        )
        assert len(r1) == 1

        # Fire 2 - should succeed
        r2 = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_ci_failure_payload(repo="org/repo", delivery_id="del-2"),
        )
        assert len(r2) == 1

        # Fire 3 - should be blocked (max_attempts=2)
        r3 = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_ci_failure_payload(repo="org/repo", delivery_id="del-3"),
        )
        assert r3 == []

    @pytest.mark.asyncio
    async def test_duplicate_delivery_prevented(self) -> None:
        """Verify that duplicate X-GitHub-Delivery IDs are rejected."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix",
            config=(("cooldown_seconds", 0),),
        )
        await reg_handler.handle(cmd)

        eval_handler = EvaluateWebhookHandler(store=store)

        # First delivery - succeeds
        r1 = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_ci_failure_payload(repo="org/repo", delivery_id="same-delivery"),
        )
        assert len(r1) == 1

        # Same delivery ID - rejected
        r2 = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_ci_failure_payload(repo="org/repo", delivery_id="same-delivery"),
        )
        assert r2 == []


@pytest.mark.integration
class TestE2EPresets:
    """E2E: Preset enable -> webhook -> workflow dispatch."""

    @pytest.mark.asyncio
    async def test_self_healing_preset_flow(self) -> None:
        """Enable self-healing preset, send CI failure, verify dispatch."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        # Enable preset
        cmd = create_preset_command(
            preset_name="self-healing",
            repository="org/repo",
            installation_id="inst-1",
            created_by="test",
        )
        aggregate = await reg_handler.handle(cmd)

        # Send CI failure
        eval_handler = EvaluateWebhookHandler(store=store)
        payload = _ci_failure_payload(repo="org/repo")

        results = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert len(results) == 1
        assert results[0].trigger_id == aggregate.trigger_id

    @pytest.mark.asyncio
    async def test_review_fix_preset_flow(self) -> None:
        """Enable review-fix preset, send review webhook, verify dispatch."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        # Enable preset
        cmd = create_preset_command(
            preset_name="review-fix",
            repository="org/repo",
        )
        aggregate = await reg_handler.handle(cmd)

        # Send review webhook
        eval_handler = EvaluateWebhookHandler(store=store)
        payload = _review_submitted_payload(repo="org/repo")

        results = await eval_handler.evaluate(
            event="pull_request_review.submitted",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert len(results) == 1
        assert results[0].trigger_id == aggregate.trigger_id

    @pytest.mark.asyncio
    async def test_review_fix_success_status_does_not_fire(self) -> None:
        """Verify that an 'approved' review doesn't trigger review-fix."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        cmd = create_preset_command(
            preset_name="review-fix",
            repository="org/repo",
        )
        await reg_handler.handle(cmd)

        eval_handler = EvaluateWebhookHandler(store=store)
        payload = _review_submitted_payload(repo="org/repo", review_state="approved")

        results = await eval_handler.evaluate(
            event="pull_request_review.submitted",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert results == []


@pytest.mark.integration
class TestE2EPauseResume:
    """E2E: Paused triggers don't fire, resumed triggers do."""

    @pytest.mark.asyncio
    async def test_paused_trigger_does_not_fire(self) -> None:
        """Verify paused triggers don't dispatch workflows."""
        store = InMemoryTriggerStore()
        reg_handler = RegisterTriggerHandler(store=store)

        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix",
        )
        aggregate = await reg_handler.handle(cmd)

        # Pause
        manage_handler = ManageTriggerHandler(store=store)
        await manage_handler.pause(
            PauseTriggerCommand(trigger_id=aggregate.trigger_id, paused_by="admin")
        )

        # Try to fire - should not work
        eval_handler = EvaluateWebhookHandler(store=store)
        results = await eval_handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_ci_failure_payload(repo="org/repo"),
        )

        assert results == []
