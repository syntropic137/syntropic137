"""HTTP endpoint for GitHub webhooks."""

from __future__ import annotations

import json
import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Request

from syn_api.routes.webhooks.processing import verify_and_process_webhook
from syn_api.routes.webhooks.push_events import _record_push_commits
from syn_api.types import Err, WebhookResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _handle_ping(body: bytes) -> dict[str, Any]:
    """Handle a GitHub ping event and return the pong response."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    return {"status": "pong", "zen": payload.get("zen", "")}


def _raise_for_webhook_error(result: Err[Any]) -> NoReturn:
    """Classify a webhook error and raise the appropriate HTTPException."""
    error_name = result.error.value if hasattr(result.error, "value") else str(result.error)
    if "signature" in error_name.lower():
        raise HTTPException(status_code=401, detail=result.message)
    if "payload" in error_name.lower():
        raise HTTPException(status_code=400, detail=result.message)
    raise HTTPException(status_code=500, detail=result.message)


def _build_webhook_response(webhook_result: WebhookResult) -> dict[str, Any]:
    """Build the HTTP response dict from a successful WebhookResult."""
    response: dict[str, Any] = {
        "status": webhook_result.status,
        "event": webhook_result.event,
    }
    if webhook_result.triggers_fired:
        response["triggers"] = [{"trigger_id": tid} for tid in webhook_result.triggers_fired]
    if webhook_result.deferred:
        response["deferred"] = [{"trigger_id": tid} for tid in webhook_result.deferred]
    return response


@router.post("/github")
async def github_webhook_endpoint(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_github_delivery: str = Header(..., alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """Handle GitHub webhooks."""
    body = await request.body()

    # Handle ping separately
    if x_github_event == "ping":
        return _handle_ping(body)

    result = await verify_and_process_webhook(
        body=body,
        event_type=x_github_event,
        delivery_id=x_github_delivery,
        signature=x_hub_signature_256,
    )

    if isinstance(result, Err):
        _raise_for_webhook_error(result)

    response = _build_webhook_response(result.value)

    # For push events, write commit observability events to the pipeline
    if x_github_event == "push":
        try:
            payload = json.loads(body)
            await _record_push_commits(payload, delivery_id=x_github_delivery)
        except Exception:
            logger.exception("Failed to record push commit events, webhook response unaffected")

    return response
