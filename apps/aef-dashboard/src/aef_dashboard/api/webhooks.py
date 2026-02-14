"""GitHub webhook endpoints.

Handles incoming webhooks from GitHub for App installation events.

Webhook Security:
- All webhooks are verified using X-Hub-Signature-256
- Payloads are validated before processing
- Events are emitted to the domain layer

See: https://docs.github.com/en/webhooks
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from aef_domain.contexts.github.domain.events.AppInstalledEvent import (
    AppInstalledEvent,
)
from aef_domain.contexts.github.domain.events.InstallationRevokedEvent import (
    InstallationRevokedEvent,
)
from aef_domain.contexts.github.domain.events.InstallationSuspendedEvent import (
    InstallationSuspendedEvent,
)
from aef_domain.contexts.github.slices.get_installation.projection import (
    get_installation_projection,
)
from aef_shared.settings.github import get_github_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def verify_github_signature(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
) -> bytes:
    """Verify the GitHub webhook signature.

    Args:
        request: The incoming request.
        x_hub_signature_256: The X-Hub-Signature-256 header.

    Returns:
        The raw request body.

    Raises:
        HTTPException: If signature verification fails.
    """
    import os

    settings = get_github_settings()
    secret = settings.webhook_secret.get_secret_value()

    # If no secret configured, check if we're in development mode
    if not secret:
        # Only allow bypass in explicit development mode
        if os.getenv("AEF_ENVIRONMENT", "production").lower() in ("development", "dev", "local"):
            logger.warning(
                "⚠️  DEVELOPMENT MODE: Webhook secret not configured - "
                "accepting without verification. Set AEF_GITHUB_WEBHOOK_SECRET in production!"
            )
            return await request.body()
        else:
            logger.error(
                "Webhook secret not configured. Set AEF_GITHUB_WEBHOOK_SECRET "
                "environment variable for production deployments."
            )
            raise HTTPException(
                status_code=500,
                detail="Webhook secret not configured on server",
            )

    # Secret is configured - require valid signature
    if x_hub_signature_256 is None:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    body = await request.body()

    # Compute expected signature
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    # Constant-time comparison
    if not hmac.compare_digest(expected, x_hub_signature_256):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    return body


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_github_delivery: str = Header(..., alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """Handle GitHub webhooks.

    Processes installation and installation_repositories events
    to keep the installation projection up to date.

    Args:
        request: The incoming request.
        x_github_event: The type of event (e.g., 'installation').
        x_github_delivery: Unique delivery ID for this webhook.
        x_hub_signature_256: HMAC signature for verification.

    Returns:
        Status response.
    """
    # Verify signature
    body = await verify_github_signature(request, x_hub_signature_256)

    logger.info(f"Received GitHub webhook: {x_github_event} (delivery: {x_github_delivery})")

    try:
        import json

        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    # Route to appropriate handler
    if x_github_event == "installation":
        return await _handle_installation_event(payload)
    elif x_github_event == "installation_repositories":
        return await _handle_installation_repos_event(payload)
    elif x_github_event == "ping":
        return {"status": "pong", "zen": payload.get("zen", "")}
    else:
        # Evaluate registered trigger rules for all other events
        return await _evaluate_trigger_rules(
            event_type=x_github_event,
            delivery_id=x_github_delivery,
            payload=payload,
        )


async def _handle_installation_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle installation webhook events.

    Actions:
    - created: App was installed
    - deleted: App was uninstalled
    - suspend: App was suspended
    - unsuspend: App was unsuspended

    Args:
        payload: The webhook payload.

    Returns:
        Status response.
    """
    action = payload.get("action", "")
    projection = get_installation_projection()

    if action == "created":
        # App was installed
        event = AppInstalledEvent.from_webhook(payload)
        projection.handle_app_installed(event)

        logger.info(
            f"GitHub App installed: {event.installation_id} "
            f"(account: {event.account_name}, repos: {len(event.repositories)})"
        )

        return {
            "status": "processed",
            "action": action,
            "installation_id": event.installation_id,
        }

    elif action == "deleted":
        # App was uninstalled
        revoked_event = InstallationRevokedEvent.from_webhook(payload)
        projection.handle_installation_revoked(revoked_event)

        logger.info(f"GitHub App uninstalled: {revoked_event.installation_id}")

        return {
            "status": "processed",
            "action": action,
            "installation_id": revoked_event.installation_id,
        }

    elif action in ("suspend", "unsuspend"):
        # Handle suspension events
        suspended_event = InstallationSuspendedEvent.from_webhook(payload, action)
        projection.handle_installation_suspended(suspended_event)

        status_msg = "suspended" if suspended_event.suspended else "unsuspended"
        logger.info(f"GitHub App {status_msg}: {suspended_event.installation_id}")

        return {
            "status": "processed",
            "action": action,
            "installation_id": suspended_event.installation_id,
        }

    else:
        logger.debug(f"Ignoring installation action: {action}")
        return {"status": "ignored", "action": action}


async def _handle_installation_repos_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle installation_repositories webhook events.

    This event fires when repositories are added or removed from an installation.

    Args:
        payload: The webhook payload.

    Returns:
        Status response.
    """
    action = payload.get("action", "")
    installation = payload.get("installation", {})
    installation_id = str(installation.get("id", ""))

    repos_added = payload.get("repositories_added", [])
    repos_removed = payload.get("repositories_removed", [])

    logger.info(
        f"Installation {installation_id} repos updated: +{len(repos_added)} -{len(repos_removed)}"
    )

    # Update the projection with repository changes
    projection = get_installation_projection()
    added_names = [r.get("full_name", "") for r in repos_added]
    removed_names = [r.get("full_name", "") for r in repos_removed]
    projection.update_repositories(installation_id, added_names, removed_names)

    return {
        "status": "processed",
        "action": action,
        "installation_id": installation_id,
        "repos_added": len(repos_added),
        "repos_removed": len(repos_removed),
    }


async def _evaluate_trigger_rules(
    event_type: str,
    delivery_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate registered trigger rules against an incoming webhook.

    This is the core dispatch logic:
    1. Find all active trigger rules matching this event type + repository
    2. Evaluate conditions for each rule
    3. Run safety guards
    4. Dispatch workflow execution for matching rules

    Args:
        event_type: GitHub event type (e.g. "check_run").
        delivery_id: X-GitHub-Delivery header for idempotency.
        payload: The webhook payload dict.

    Returns:
        Status response with triggered execution IDs.
    """
    from aef_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
        EvaluateWebhookHandler,
        TriggerDeferredResult,
        TriggerMatchResult,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    action = payload.get("action", "")
    full_event = f"{event_type}.{action}" if action else event_type
    repository = payload.get("repository", {}).get("full_name", "")
    installation_id = str(payload.get("installation", {}).get("id", ""))

    # Inject delivery ID for idempotency checking
    payload["_delivery_id"] = delivery_id

    # Find matching rules and dispatch (with debouncer for retry support)
    from aef_adapters.storage.repositories import get_trigger_repository
    from aef_domain.contexts.github.slices.evaluate_webhook.debouncer import (
        get_debouncer,
    )

    store = get_trigger_store()

    async def _post_activation_comment(result: TriggerMatchResult, p: dict) -> None:
        """Post PR activation comment when a trigger fires (immediate or deferred)."""
        from aef_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
            _extract_pr_number,
        )

        pr_number = _extract_pr_number(p)
        repo_name = p.get("repository", {}).get("full_name", "")
        if not pr_number or not repo_name:
            return
        try:
            from aef_adapters.github.client import get_github_client

            client = get_github_client()
            owner, name = repo_name.split("/", 1)
            trigger_info = await store.get(result.trigger_id)
            trigger_name = trigger_info.name if trigger_info else result.trigger_id
            workflow_id = trigger_info.workflow_id if trigger_info else "unknown"
            await client.api_post(
                f"/repos/{owner}/{name}/issues/{pr_number}/comments",
                json={"body": f"**{trigger_name}** trigger activated — running `{workflow_id}`..."},
            )
        except Exception:
            logger.warning("Failed to post activation comment", exc_info=True)

    handler = EvaluateWebhookHandler(
        store=store,
        repository=get_trigger_repository(),
        debouncer=get_debouncer(),
        on_fire=_post_activation_comment,
    )
    results = await handler.evaluate(
        event=full_event,
        repository=repository,
        installation_id=installation_id,
        payload=payload,
    )

    if not results:
        logger.debug(f"No matching triggers for {full_event} on {repository}")
        return {"status": "ignored", "event": full_event, "reason": "No matching triggers"}

    # Partition into fired vs deferred
    fired = [r for r in results if isinstance(r, TriggerMatchResult)]
    deferred = [r for r in results if isinstance(r, TriggerDeferredResult)]

    deferred_list = [
        {"trigger_id": d.trigger_id, "reason": d.reason, "defer_seconds": d.defer_seconds}
        for d in deferred
    ]

    if fired:
        logger.info(f"Triggered {len(fired)} workflow(s) for {full_event} on {repository}")
        return {
            "status": "triggered",
            "event": full_event,
            "triggers": [
                {"trigger_id": r.trigger_id, "execution_id": r.execution_id} for r in fired
            ],
            "deferred": deferred_list,
        }

    logger.info(f"Deferred {len(deferred)} trigger(s) for {full_event} on {repository}")
    return {
        "status": "deferred",
        "event": full_event,
        "deferred": deferred_list,
    }
