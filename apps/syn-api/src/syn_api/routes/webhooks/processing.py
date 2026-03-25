"""Webhook processing orchestrator — verifies, parses, evaluates, and acknowledges."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from syn_api._wiring import ensure_connected
from syn_api.routes.webhooks.acknowledgments import _post_trigger_acknowledgments
from syn_api.routes.webhooks.handlers import _evaluate_triggers, _handle_installation_event
from syn_api.routes.webhooks.signature import verify_webhook_signature
from syn_api.types import Err, GitHubError, Ok, Result, WebhookResult

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)


async def verify_and_process_webhook(
    body: bytes,
    event_type: str,
    delivery_id: str,  # noqa: ARG001
    signature: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[WebhookResult, GitHubError]:
    """Verify a GitHub webhook signature and process the event.

    Orchestrator that delegates to focused helpers for signature
    verification, installation handling, trigger evaluation, and
    acknowledgment posting.
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

    # 4. Evaluate triggers
    compound_event = f"{event_type}.{action}" if action else event_type
    triggers_fired, deferred = await _evaluate_triggers(
        event_type, action, payload, installation_id
    )

    # 5. Post acknowledgments
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
