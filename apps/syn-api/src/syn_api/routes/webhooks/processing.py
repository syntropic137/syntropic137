"""Webhook processing orchestrator — verifies, parses, evaluates, and acknowledges."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from syn_api._wiring import ensure_connected, get_event_pipeline, get_webhook_health_tracker
from syn_api.routes.webhooks.acknowledgments import _post_trigger_acknowledgments
from syn_api.routes.webhooks.handlers import _handle_installation_event
from syn_api.routes.webhooks.signature import verify_webhook_signature
from syn_api.types import Err, GitHubError, Ok, Result, WebhookResult
from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)

logger = logging.getLogger(__name__)


async def verify_and_process_webhook(
    body: bytes,
    event_type: str,
    delivery_id: str,
    signature: str | None = None,
) -> Result[WebhookResult, GitHubError]:
    """Verify a GitHub webhook signature and process the event.

    Orchestrator that delegates to focused helpers for signature
    verification, installation handling, trigger evaluation (via the
    unified EventPipeline), and acknowledgment posting.
    """
    await ensure_connected()

    # 1. Verify signature
    sig_result = verify_webhook_signature(body, signature)
    if isinstance(sig_result, Err):
        return sig_result

    # 2. Parse payload
    try:
        payload: dict[str, Any] = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return Err(GitHubError.INVALID_PAYLOAD, message=f"Invalid JSON payload: {e}")

    action = payload.get("action", "")
    installation_id = str(payload.get("installation", {}).get("id", ""))

    # 3. Handle installation events
    await _handle_installation_event(event_type, action, payload)

    # 4. Route through unified pipeline (ISS-386)
    repository = payload.get("repository", {}).get("full_name", "")
    dedup_key = compute_dedup_key(event_type, action, payload)

    event = NormalizedEvent(
        event_type=event_type,
        action=action,
        repository=repository,
        installation_id=installation_id,
        dedup_key=dedup_key,
        source=EventSource.WEBHOOK,
        payload=payload,
        received_at=datetime.now(UTC),
        delivery_id=delivery_id,
    )

    # Record webhook receipt for health tracking (poller mode switching)
    get_webhook_health_tracker().record_received()

    pipeline = get_event_pipeline()
    pipeline_result = await pipeline.ingest(event)

    triggers_fired = pipeline_result.triggers_fired
    deferred = pipeline_result.deferred

    # 5. Post acknowledgments
    compound_event = f"{event_type}.{action}" if action else event_type
    if triggers_fired:
        await _post_trigger_acknowledgments(
            event_type, payload, triggers_fired, compound_event, installation_id
        )

    return Ok(
        WebhookResult(
            status="processed",
            event=event_type,
            triggers_fired=triggers_fired,
            deferred=deferred,
        )
    )
