"""Offline integration tests for the trigger pipeline.

Tests run fully offline — no Docker, no network, no API keys.
Verifies: webhook → trigger evaluation → workflow dispatch inputs.

Uses APP_ENVIRONMENT=test for in-memory adapters.

See ADR-041: Offline Development Mode and Webhook Recording.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

import pytest

from syn_api.types import Err, Ok

os.environ.setdefault("APP_ENVIRONMENT", "test")

_TEST_WEBHOOK_SECRET = "test-webhook-secret"
os.environ["SYN_GITHUB_WEBHOOK_SECRET"] = _TEST_WEBHOOK_SECRET

# Path to webhook fixtures (relative to repo root)
_FIXTURES_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "webhooks"


@pytest.fixture(autouse=True)
async def _reset_storage():
    """Reset in-memory storage between tests and seed required workflows."""
    import syn_api._wiring
    from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
        reset_trigger_store,
    )
    from syn_shared.settings.github import reset_github_settings

    reset_trigger_store()
    reset_github_settings()
    syn_api._wiring._test_trigger_repo = None

    # Seed the "self-heal-pr" workflow that trigger presets reference
    from syn_adapters.storage import get_event_publisher, get_workflow_repository
    from syn_api._wiring import ensure_connected
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

    await ensure_connected()
    handler = CreateWorkflowTemplateHandler(
        repository=get_workflow_repository(),
        event_publisher=get_event_publisher(),
    )
    workflow_repo = get_workflow_repository()
    if not await workflow_repo.exists("self-heal-pr"):
        await handler.handle(
            CreateWorkflowTemplateCommand(
                aggregate_id="self-heal-pr",
                name="Self-Heal PR",
                description="Workflow for self-healing CI and review fixes",
                workflow_type="implementation",
                classification="standard",
                repository_url="https://github.com/demo/offline-repo",
                phases=[
                    {
                        "phase_id": "diagnose",
                        "name": "diagnose",
                        "order": 1,
                        "description": "Analyze failure and identify root cause",
                    },
                    {
                        "phase_id": "fix",
                        "name": "fix",
                        "order": 2,
                        "description": "Apply automated fix",
                    },
                ],
            )
        )

    yield
    reset_trigger_store()
    syn_api._wiring._test_trigger_repo = None


def _sign(body: bytes) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    return "sha256=" + hmac.new(_TEST_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _load_fixture(filename: str) -> tuple[dict, str]:
    """Load a webhook fixture and return (payload, event_type).

    Reads a JSONL fixture file and returns the body payload
    and the GitHub event type.
    """
    filepath = _FIXTURES_DIR / filename
    lines = filepath.read_text().strip().splitlines()

    # Parse metadata
    metadata = json.loads(lines[0])
    assert metadata.get("_type") == "metadata"
    event_type = metadata["event_type"]

    # Parse first event entry
    entry = json.loads(lines[1])
    payload = entry["body"]

    return payload, event_type


@pytest.mark.integration
async def test_self_healing_check_run_failure():
    """Full loop: check_run failure → self-healing trigger fires."""
    from syn_api.routes.webhooks import verify_and_process_webhook
    from syn_api.routes.triggers import enable_preset, list_triggers

    # Seed self-healing trigger preset
    result = await enable_preset(
        preset_name="self-healing",
        repository="demo/offline-repo",
    )
    assert isinstance(result, Ok), f"Failed to seed self-healing preset: {result}"

    # Verify trigger was created
    triggers = await list_triggers(repository="demo/offline-repo")
    assert isinstance(triggers, Ok)
    assert len(triggers.value) >= 1

    # Find the self-healing trigger
    sh_triggers = [
        t
        for t in triggers.value
        if "self-healing" in t.name.lower() or "self_healing" in t.name.lower()
    ]
    assert len(sh_triggers) >= 1, (
        f"No self-healing trigger found. Triggers: {[t.name for t in triggers.value]}"
    )

    # Load fixture and inject webhook
    payload, event_type = _load_fixture("check_run_failure.jsonl")
    body = json.dumps(payload).encode()

    result = await verify_and_process_webhook(
        body=body,
        event_type=event_type,
        delivery_id="test-delivery-001",
        signature=_sign(body),
    )

    # Assert webhook was processed
    assert isinstance(result, Ok), f"Webhook processing failed: {result}"
    assert result.value.status == "processed"
    assert result.value.event == "check_run"

    # Assert trigger fired
    assert len(result.value.triggers_fired) >= 1, (
        f"Expected self-healing trigger to fire. "
        f"Fired: {result.value.triggers_fired}, Deferred: {result.value.deferred}"
    )


@pytest.mark.integration
async def test_issue_comment_trigger():
    """issue_comment.created → review-fix trigger fires."""
    from syn_api.routes.webhooks import verify_and_process_webhook
    from syn_api.routes.triggers import enable_preset, list_triggers

    # Seed review-fix trigger preset
    result = await enable_preset(
        preset_name="review-fix",
        repository="demo/offline-repo",
    )
    assert isinstance(result, Ok), f"Failed to seed review-fix preset: {result}"

    # Verify trigger was created
    triggers = await list_triggers(repository="demo/offline-repo")
    assert isinstance(triggers, Ok)
    assert len(triggers.value) >= 1

    # Load fixture and inject webhook
    payload, event_type = _load_fixture("issue_comment_command.jsonl")
    body = json.dumps(payload).encode()

    result = await verify_and_process_webhook(
        body=body,
        event_type=event_type,
        delivery_id="test-delivery-002",
        signature=_sign(body),
    )

    # Assert webhook was processed
    assert isinstance(result, Ok), f"Webhook processing failed: {result}"
    assert result.value.status == "processed"
    assert result.value.event == "issue_comment"


@pytest.mark.integration
async def test_installation_event_does_not_crash():
    """installation.created event is handled gracefully."""
    from syn_api.routes.webhooks import verify_and_process_webhook

    payload, event_type = _load_fixture("installation_created.jsonl")
    body = json.dumps(payload).encode()

    result = await verify_and_process_webhook(
        body=body,
        event_type=event_type,
        delivery_id="test-delivery-003",
        signature=_sign(body),
    )

    # Should process without error (may not fire triggers)
    assert isinstance(result, Ok), f"Webhook processing failed: {result}"
    assert result.value.status == "processed"
    assert result.value.event == "installation"


@pytest.mark.integration
async def test_webhook_with_no_matching_triggers():
    """Webhook for a repo with no triggers returns empty triggers_fired."""
    from syn_api.routes.webhooks import verify_and_process_webhook

    payload, event_type = _load_fixture("check_run_failure.jsonl")
    body = json.dumps(payload).encode()

    # Don't seed any triggers — inject webhook directly
    result = await verify_and_process_webhook(
        body=body,
        event_type=event_type,
        delivery_id="test-delivery-004",
        signature=_sign(body),
    )

    assert isinstance(result, Ok), f"Webhook processing failed: {result}"
    assert result.value.triggers_fired == []


@pytest.mark.integration
async def test_invalid_json_payload():
    """Invalid JSON payload returns error."""
    from syn_api.routes.webhooks import verify_and_process_webhook

    body = b"not json"
    result = await verify_and_process_webhook(
        body=body,
        event_type="check_run",
        delivery_id="test-delivery-005",
        signature=_sign(body),
    )

    assert isinstance(result, Err)


@pytest.mark.integration
async def test_preset_dedup():
    """Enabling the same preset twice is idempotent (returns error, not duplicate)."""
    from syn_api.routes.triggers import enable_preset, list_triggers

    result1 = await enable_preset(preset_name="self-healing", repository="demo/offline-repo")
    assert isinstance(result1, Ok)

    result2 = await enable_preset(preset_name="self-healing", repository="demo/offline-repo")
    assert isinstance(result2, Err), "Second enable_preset should be rejected as duplicate"

    # Verify only one trigger exists
    triggers = await list_triggers(repository="demo/offline-repo")
    assert isinstance(triggers, Ok)
    sh_count = sum(1 for t in triggers.value if t.status != "deleted")
    assert sh_count == 1
