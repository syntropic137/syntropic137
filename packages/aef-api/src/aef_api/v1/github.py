"""GitHub operations — repositories, installations, and webhook processing.

Consolidated module for all GitHub concerns. Trigger operations
remain in ``aef_api.v1.triggers``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import TYPE_CHECKING, Any

from aef_api._wiring import (
    ensure_connected,
    get_github_settings,
    get_trigger_repo,
    get_trigger_store,
)
from aef_api.types import Err, GitHubError, Ok, Result, WebhookResult

if TYPE_CHECKING:
    from aef_api.auth import AuthContext

logger = logging.getLogger(__name__)


async def list_repos(
    installation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[dict[str, Any]], GitHubError]:
    """List GitHub repositories accessible via the GitHub App.

    Args:
        installation_id: Optional filter by installation ID.
        limit: Maximum results to return.
        offset: Pagination offset.
        auth: Optional authentication context.

    Returns:
        Ok(list[dict]) on success, Err(GitHubError) on failure.
    """
    await ensure_connected()
    try:
        from aef_domain.contexts.github.slices.get_installation.projection import (
            get_installation_projection,
        )

        projection = get_installation_projection()

        if installation_id:
            inst = projection.get(installation_id)
            if inst is None:
                return Err(
                    GitHubError.NOT_FOUND,
                    message=f"Installation {installation_id} not found",
                )
            repos = getattr(inst, "repositories", [])
        else:
            active = projection.get_all_active()
            repos = []
            for inst in active:
                for repo in getattr(inst, "repositories", []):
                    repos.append(repo)

        # Apply pagination
        page = repos[offset : offset + limit]
        return Ok([{"full_name": r} if isinstance(r, str) else r for r in page])
    except Exception as e:
        return Err(GitHubError.NOT_FOUND, message=str(e))


async def get_installation(
    installation_id: str,
    auth: AuthContext | None = None,
) -> Result[dict[str, Any], GitHubError]:
    """Get details about a GitHub App installation.

    Args:
        installation_id: The installation ID to look up.
        auth: Optional authentication context.

    Returns:
        Ok(dict) on success, Err(GitHubError) on failure.
    """
    await ensure_connected()
    try:
        from aef_domain.contexts.github.slices.get_installation.projection import (
            get_installation_projection,
        )

        projection = get_installation_projection()
        inst = projection.get(installation_id)

        if inst is None:
            return Err(
                GitHubError.NOT_FOUND,
                message=f"Installation {installation_id} not found",
            )

        return Ok(
            {
                "installation_id": installation_id,
                "account": getattr(inst, "account", None),
                "status": getattr(inst, "status", "active"),
                "repositories": getattr(inst, "repositories", []),
                "created_at": str(getattr(inst, "created_at", "")),
            }
        )
    except Exception as e:
        return Err(GitHubError.NOT_FOUND, message=str(e))


async def verify_and_process_webhook(
    body: bytes,
    event_type: str,
    delivery_id: str,
    signature: str | None = None,
    auth: AuthContext | None = None,
) -> Result[WebhookResult, GitHubError]:
    """Verify a GitHub webhook signature and process the event.

    Args:
        body: Raw request body bytes.
        event_type: GitHub event type header (X-GitHub-Event).
        delivery_id: GitHub delivery ID header (X-GitHub-Delivery).
        signature: GitHub signature header (X-Hub-Signature-256).
        auth: Optional authentication context.

    Returns:
        Ok(WebhookResult) on success, Err(GitHubError) on failure.
    """
    import json

    await ensure_connected()

    # Verify signature if webhook secret is configured
    try:
        github_settings = get_github_settings()
        secret = github_settings.webhook_secret.get_secret_value()

        if secret and signature:
            expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return Err(GitHubError.INVALID_SIGNATURE, message="Invalid webhook signature")
        elif secret and not signature:
            return Err(GitHubError.INVALID_SIGNATURE, message="Missing webhook signature")
    except Exception:
        logger.exception("Failed to verify webhook signature")

    # Parse payload
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return Err(GitHubError.INVALID_PAYLOAD, message=f"Invalid JSON payload: {e}")

    # Handle installation events
    if event_type in ("installation", "installation_repositories"):
        try:
            from aef_domain.contexts.github.slices.get_installation.projection import (
                get_installation_projection,
            )

            projection = get_installation_projection()
            action = payload.get("action", "")

            if event_type == "installation" and action == "created":
                from aef_domain.contexts.github.domain.events import AppInstalledEvent

                event = AppInstalledEvent.from_webhook(payload)
                projection.handle_app_installed(event)
        except Exception:
            logger.exception("Failed to handle installation event")

    # Evaluate triggers
    #
    # GitHub sends the event type in X-GitHub-Event (e.g. "check_run") and
    # the action in the payload body (e.g. "completed").  Trigger presets
    # register with compound events like "check_run.completed", so we
    # compose `{event_type}.{action}` to match.
    triggers_fired: list[str] = []
    deferred: list[str] = []
    try:
        repository = payload.get("repository", {}).get("full_name", "")
        installation_id = str(payload.get("installation", {}).get("id", ""))

        # Compose compound event (e.g. "issue_comment.created")
        action = payload.get("action", "")
        compound_event = f"{event_type}.{action}" if action else event_type

        from aef_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
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

    # Post acknowledgment reaction on comment-triggered events
    if triggers_fired and event_type == "issue_comment":
        comment_id = payload.get("comment", {}).get("id")
        repo_full_name = payload.get("repository", {}).get("full_name", "")
        if comment_id and repo_full_name:
            await _post_comment_reaction(repo_full_name, comment_id, "eyes")

    return Ok(
        WebhookResult(
            status="processed",
            event=event_type,
            triggers_fired=triggers_fired,
            deferred=deferred,
        )
    )


async def _post_comment_reaction(
    repo_full_name: str,
    comment_id: int,
    reaction: str = "eyes",
) -> None:
    """Post a reaction on a GitHub issue/PR comment (best-effort).

    Uses the GitHub App installation token to call the Reactions API.
    Failures are logged but do not propagate.
    """
    try:
        from aef_adapters.github.client import get_github_client

        client = get_github_client()
        await client.api_post(
            f"/repos/{repo_full_name}/issues/comments/{comment_id}/reactions",
            json={"content": reaction},
        )
        logger.info("Posted %s reaction on comment %s in %s", reaction, comment_id, repo_full_name)
    except Exception:
        logger.debug(
            "Could not post reaction on comment %s (GitHub App may not be configured)",
            comment_id,
        )
