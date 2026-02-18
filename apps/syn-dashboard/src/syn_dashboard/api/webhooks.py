"""GitHub webhook endpoints — thin wrapper over syn_api."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

import syn_api.v1.github as gh
from syn_api.types import Err

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_github_delivery: str = Header(..., alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """Handle GitHub webhooks.

    Processes installation and other events via syn_api.v1.github.
    """
    body = await request.body()

    # Handle ping separately (no processing needed)
    if x_github_event == "ping":
        import json

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        return {"status": "pong", "zen": payload.get("zen", "")}

    # Process through syn_api
    result = await gh.verify_and_process_webhook(
        body=body,
        event_type=x_github_event,
        delivery_id=x_github_delivery,
        signature=x_hub_signature_256,
    )

    if isinstance(result, Err):
        error_name = result.error.value if hasattr(result.error, "value") else str(result.error)
        if "signature" in error_name.lower():
            raise HTTPException(status_code=401, detail=result.message)
        if "payload" in error_name.lower():
            raise HTTPException(status_code=400, detail=result.message)
        raise HTTPException(status_code=500, detail=result.message)

    webhook_result = result.value
    response: dict[str, Any] = {
        "status": webhook_result.status,
        "event": webhook_result.event,
    }

    if webhook_result.triggers_fired:
        response["triggers"] = [{"trigger_id": tid} for tid in webhook_result.triggers_fired]

    if webhook_result.deferred:
        response["deferred"] = [{"trigger_id": tid} for tid in webhook_result.deferred]

    return response
