"""GitHub webhook endpoints — thin wrapper over syn_api."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

import syn_api.v1.github as gh
from syn_api._wiring import get_event_store_instance, get_realtime
from syn_api.types import Err

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# --- Signature-failure rate limiter ---
# Tracks failed signature attempts per IP. After _MAX_FAILURES within
# _WINDOW_SECONDS, the IP is blocked with 429 before we even check the
# signature — protecting against brute-force and replay attacks.
_MAX_FAILURES = 5
_WINDOW_SECONDS = 60
_sig_failures: dict[str, list[float]] = defaultdict(list)


def _check_sig_rate_limit(client_ip: str) -> None:
    """Raise 429 if this IP has too many recent signature failures."""
    now = time.monotonic()
    attempts = _sig_failures[client_ip]
    # Prune old entries
    _sig_failures[client_ip] = [t for t in attempts if now - t < _WINDOW_SECONDS]
    if len(_sig_failures[client_ip]) >= _MAX_FAILURES:
        logger.warning("Webhook rate limit: %s blocked (%d failures)", client_ip, len(_sig_failures[client_ip]))
        raise HTTPException(status_code=429, detail="Too many failed signature attempts")


def _record_sig_failure(client_ip: str) -> None:
    """Record a signature verification failure for rate limiting."""
    _sig_failures[client_ip].append(time.monotonic())


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
    client_ip = request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")
    body = await request.body()

    # Handle ping separately (no processing needed)
    if x_github_event == "ping":
        import json

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        return {"status": "pong", "zen": payload.get("zen", "")}

    # Check if this IP is rate-limited from too many signature failures
    _check_sig_rate_limit(client_ip)

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
            _record_sig_failure(client_ip)
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

    # For push events, write commit observability events to the pipeline
    if x_github_event == "push":
        try:
            import json

            payload = json.loads(body)
            await _record_push_commits(payload, delivery_id=x_github_delivery)
        except Exception:
            logger.exception("Failed to record push commit events — webhook response unaffected")

    return response


async def _record_push_commits(payload: dict[str, Any], delivery_id: str) -> None:
    """Write git_commit observability events for each commit in a push payload.

    Each commit is stored as a git_commit event in the observability pipeline
    and broadcast to the global /ws/activity feed for the dashboard live view.
    """
    commits: list[dict[str, Any]] = payload.get("commits", [])
    if not commits:
        return

    repo = payload.get("repository", {}).get("full_name", "unknown/unknown")
    ref: str = payload.get("ref", "")
    branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ref

    store = get_event_store_instance()
    await store.initialize()
    realtime = get_realtime()

    for commit in commits:
        commit_hash: str = commit.get("id", "")
        if not commit_hash:
            continue

        data: dict[str, Any] = {
            "commit_hash": commit_hash,
            "message": commit.get("message", ""),
            "author": commit.get("author", {}).get("name", "unknown"),
            "repository": repo,
            "branch": branch,
            "url": commit.get("url", f"https://github.com/{repo}/commit/{commit_hash}"),
            "timestamp": commit.get("timestamp", datetime.now(UTC).isoformat()),
        }

        await store.insert_one(
            {
                "event_type": "git_commit",
                "session_id": f"github_delivery:{delivery_id}",
                "data": data,
            }
        )

        await realtime.broadcast_global("git_commit", data)

        logger.info(
            "Recorded git commit event",
            extra={"commit_hash": commit_hash[:7], "repo": repo, "branch": branch},
        )
