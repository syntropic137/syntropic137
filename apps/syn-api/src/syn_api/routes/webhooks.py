"""GitHub webhook endpoints and service operations.

Handles webhook signature verification, installation events, trigger
evaluation, and acknowledgment posting.  Also exposes service functions
for listing GitHub App repos and installation details.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Request

from syn_api._wiring import (
    ensure_connected,
    get_event_store_instance,
    get_github_settings,
    get_realtime,
    get_trigger_repo,
    get_trigger_store,
)
from syn_api.types import Err, GitHubError, Ok, Result, WebhookResult

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# --- Signature-failure rate limiter ---
_MAX_FAILURES = 5
_WINDOW_SECONDS = 60
_sig_failures: dict[str, list[float]] = defaultdict(list)


def _check_sig_rate_limit(client_ip: str) -> None:
    """Raise 429 if this IP has too many recent signature failures."""
    now = time.monotonic()
    attempts = _sig_failures[client_ip]
    _sig_failures[client_ip] = [t for t in attempts if now - t < _WINDOW_SECONDS]
    if len(_sig_failures[client_ip]) >= _MAX_FAILURES:
        logger.warning(
            "Webhook rate limit: %s blocked (%d failures)", client_ip, len(_sig_failures[client_ip])
        )
        raise HTTPException(status_code=429, detail="Too many failed signature attempts")


def _record_sig_failure(client_ip: str) -> None:
    """Record a signature verification failure for rate limiting."""
    _sig_failures[client_ip].append(time.monotonic())


# =============================================================================
# Internal helpers (decomposed from verify_and_process_webhook)
# =============================================================================


def _verify_signature(body: bytes, signature: str | None, webhook_secret: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature.

    Returns True when the signature is valid.
    Raises ``ValueError`` with a human-readable message on any failure.
    """
    if not webhook_secret:
        raise ValueError("Webhook secret not configured — rejecting unverified payload")
    if not signature:
        raise ValueError("Missing webhook signature")

    expected = "sha256=" + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid webhook signature")
    return True


async def _handle_installation_event(event_type: str, action: str, payload: dict[str, Any]) -> None:
    """Process installation created/deleted events (best-effort)."""
    if event_type not in ("installation", "installation_repositories"):
        return

    try:
        from syn_domain.contexts.github.slices.get_installation.projection import (
            get_installation_projection,
        )

        projection = get_installation_projection()

        if event_type == "installation" and action == "created":
            from syn_domain.contexts.github.domain.events import AppInstalledEvent

            event = AppInstalledEvent.from_webhook(payload)
            await projection.handle_app_installed(event)
    except Exception:
        logger.exception("Failed to handle installation event")


async def _evaluate_triggers(
    event_type: str,
    action: str,
    payload: dict[str, Any],
    installation_id: str,
) -> tuple[list[str], list[str]]:
    """Evaluate webhook triggers and return (fired, deferred) trigger ID lists."""
    triggers_fired: list[str] = []
    deferred: list[str] = []
    compound_event = f"{event_type}.{action}" if action else event_type
    repository = payload.get("repository", {}).get("full_name", "")

    try:
        from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
            EvaluateWebhookHandler,
            TriggerDeferredResult,
            TriggerMatchResult,
        )

        handler = EvaluateWebhookHandler(
            store=get_trigger_store(),
            repository=get_trigger_repo(),
        )
        results = await handler.evaluate(
            event=compound_event,
            repository=repository,
            installation_id=installation_id,
            payload=payload,
        )

        for r in results:
            if isinstance(r, TriggerMatchResult):
                triggers_fired.append(r.trigger_id)
            elif isinstance(r, TriggerDeferredResult):
                deferred.append(r.trigger_id)
    except Exception:
        logger.exception("Failed to evaluate webhook triggers")

    return triggers_fired, deferred


def _extract_pr_number(event_type: str, payload: dict[str, Any]) -> int | None:
    """Extract the PR number from a webhook payload (best-effort)."""
    if event_type == "issue_comment":
        if payload.get("issue", {}).get("pull_request"):
            return payload["issue"].get("number")
    elif event_type == "check_run":
        prs = payload.get("check_run", {}).get("pull_requests", [])
        if prs:
            return prs[0].get("number")
    elif event_type in ("pull_request_review", "pull_request"):
        return payload.get("pull_request", {}).get("number")
    return None


# Trigger name labels for human-readable status comments
_TRIGGER_LABELS: dict[str, str] = {
    "check_run.completed": "Self-Heal",
    "pull_request_review.submitted": "Review Fix",
    "issue_comment.created": "Command",
}


async def _post_trigger_started_comment(
    repo_full_name: str,
    pr_number: int,
    trigger_ids: list[str],
    compound_event: str,
    installation_id: str | None = None,
) -> None:
    """Post a deterministic status comment on the PR when a trigger fires.

    Best-effort — failures are logged but do not block webhook processing.
    """
    label = _TRIGGER_LABELS.get(compound_event, "Workflow")
    trigger_list = ", ".join(f"`{tid}`" for tid in trigger_ids)
    body = f"⚡ **{label} Starting**\n\nTrigger {trigger_list} fired on `{compound_event}` — dispatching workflow."

    try:
        from syn_adapters.github.client import get_github_client

        client = get_github_client()
        await client.api_post(
            f"/repos/{repo_full_name}/issues/{pr_number}/comments",
            json={"body": body},
            installation_id=installation_id,
        )
        logger.info("Posted trigger-started comment on %s#%s", repo_full_name, pr_number)
    except Exception:
        logger.warning(
            "Could not post trigger-started comment on %s#%s (GitHub App may not be configured)",
            repo_full_name,
            pr_number,
            exc_info=True,
        )


async def _post_comment_reaction(
    repo_full_name: str,
    comment_id: int,
    reaction: str = "rocket",
    installation_id: str | None = None,
) -> None:
    """Post a reaction on a GitHub issue/PR comment (best-effort)."""
    try:
        from syn_adapters.github.client import get_github_client

        client = get_github_client()
        await client.api_post(
            f"/repos/{repo_full_name}/issues/comments/{comment_id}/reactions",
            json={"content": reaction},
            installation_id=installation_id,
        )
        logger.info("Posted %s reaction on comment %s in %s", reaction, comment_id, repo_full_name)
    except Exception:
        logger.debug(
            "Could not post reaction on comment %s (GitHub App may not be configured)",
            comment_id,
        )


async def _post_trigger_acknowledgments(
    event_type: str,
    payload: dict[str, Any],
    triggers_fired: list[str],
    compound_event: str,
    installation_id: str,
) -> None:
    """Post GitHub comment/reaction acknowledgments for fired triggers (best-effort)."""
    repo_full_name = payload.get("repository", {}).get("full_name", "")

    # React to the comment that triggered the workflow
    if event_type == "issue_comment":
        comment_id = payload.get("comment", {}).get("id")
        if comment_id and repo_full_name:
            await _post_comment_reaction(repo_full_name, comment_id, "rocket", installation_id)

    # Post deterministic "starting" comment on the PR
    pr_number = _extract_pr_number(event_type, payload)
    if pr_number and repo_full_name:
        await _post_trigger_started_comment(
            repo_full_name,
            pr_number,
            triggers_fired,
            compound_event,
            installation_id,
        )


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def list_repos(
    installation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[dict[str, Any]], GitHubError]:
    """List GitHub repositories accessible via the GitHub App."""
    await ensure_connected()
    try:
        from syn_domain.contexts.github.slices.get_installation.projection import (
            get_installation_projection,
        )

        projection = get_installation_projection()

        if installation_id:
            inst = await projection.get(installation_id)
            if inst is None:
                return Err(
                    GitHubError.NOT_FOUND,
                    message=f"Installation {installation_id} not found",
                )
            repos = inst.repositories if hasattr(inst, "repositories") else []
        else:
            active = await projection.get_all_active()
            repos = []
            for inst in active:
                for repo in inst.repositories:
                    repos.append(repo)

        page = repos[offset : offset + limit]
        return Ok([{"full_name": r} if isinstance(r, str) else r for r in page])
    except Exception as e:
        return Err(GitHubError.NOT_FOUND, message=str(e))


async def get_installation(
    installation_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[dict[str, Any], GitHubError]:
    """Get details about a GitHub App installation."""
    await ensure_connected()
    try:
        from syn_domain.contexts.github.slices.get_installation.projection import (
            get_installation_projection,
        )

        projection = get_installation_projection()
        inst = await projection.get(installation_id)

        if inst is None:
            return Err(
                GitHubError.NOT_FOUND,
                message=f"Installation {installation_id} not found",
            )

        return Ok(
            {
                "installation_id": installation_id,
                "account": inst.account_name,
                "status": inst.status,
                "repositories": inst.repositories,
                "created_at": str(inst.installed_at or ""),
            }
        )
    except Exception as e:
        return Err(GitHubError.NOT_FOUND, message=str(e))


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
    try:
        secret = get_github_settings().webhook_secret.get_secret_value()
        _verify_signature(body, signature, secret)
    except ValueError as exc:
        return Err(GitHubError.INVALID_SIGNATURE, message=str(exc))
    except Exception:
        logger.exception("Failed to verify webhook signature")
        return Err(GitHubError.INVALID_SIGNATURE, message="Signature verification failed — rejecting payload")

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
    triggers_fired, deferred = await _evaluate_triggers(event_type, action, payload, installation_id)

    # 5. Post acknowledgments
    if triggers_fired:
        await _post_trigger_acknowledgments(event_type, payload, triggers_fired, compound_event, installation_id)

    return Ok(
        WebhookResult(
            status="processed",
            event=event_type,
            triggers_fired=triggers_fired,
            deferred=deferred,
        )
    )


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.post("/github")
async def github_webhook_endpoint(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_github_delivery: str = Header(..., alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """Handle GitHub webhooks."""
    client_ip = request.headers.get(
        "X-Real-IP", request.client.host if request.client else "unknown"
    )
    body = await request.body()

    # Handle ping separately
    if x_github_event == "ping":
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        return {"status": "pong", "zen": payload.get("zen", "")}

    _check_sig_rate_limit(client_ip)

    result = await verify_and_process_webhook(
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
            payload = json.loads(body)
            await _record_push_commits(payload, delivery_id=x_github_delivery)
        except Exception:
            logger.exception("Failed to record push commit events — webhook response unaffected")

    return response


async def _record_push_commits(payload: dict[str, Any], delivery_id: str) -> None:
    """Write git_commit observability events for each commit in a push payload."""
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
