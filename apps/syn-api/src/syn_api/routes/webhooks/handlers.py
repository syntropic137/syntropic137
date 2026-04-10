"""Installation event handling and trigger evaluation."""

from __future__ import annotations

import logging
from typing import Any

from syn_api._wiring import get_trigger_repo, get_trigger_store

logger = logging.getLogger(__name__)


async def _apply_installation_created(payload: dict[str, Any]) -> None:
    """Create and persist an AppInstalledEvent from webhook payload."""
    from syn_domain.contexts.github.domain.events import AppInstalledEvent
    from syn_domain.contexts.github.slices.get_installation.projection import (
        get_installation_projection,
    )

    event = AppInstalledEvent.from_webhook(payload)
    projection = get_installation_projection()
    await projection.handle_app_installed(event)


async def _apply_installation_repositories_changed(
    payload: dict[str, Any],
    action: str,  # noqa: ARG001 — reserved for future per-action logic
) -> None:
    """Update the projection when repos are added or removed from an installation."""
    from syn_domain.contexts.github.slices.get_installation.projection import (
        get_installation_projection,
    )

    installation_id = str(payload.get("installation", {}).get("id", ""))
    if not installation_id:
        logger.warning("installation_repositories event missing installation.id")
        return

    repos_added = [
        r["full_name"]
        for r in payload.get("repositories_added", [])
        if r.get("full_name")
    ]
    repos_removed = [
        r["full_name"]
        for r in payload.get("repositories_removed", [])
        if r.get("full_name")
    ]

    projection = get_installation_projection()
    await projection.update_repositories(installation_id, repos_added, repos_removed)


async def _handle_installation_event(event_type: str, action: str, payload: dict[str, Any]) -> None:
    """Process installation created/deleted events (best-effort)."""
    if event_type not in ("installation", "installation_repositories"):
        return

    try:
        if event_type == "installation" and action == "created":
            await _apply_installation_created(payload)
        elif event_type == "installation_repositories":
            await _apply_installation_repositories_changed(payload, action)
    except Exception:
        logger.exception("Failed to handle installation event")


def _classify_trigger_results(results: list[Any]) -> tuple[list[str], list[str]]:
    """Separate trigger evaluation results into (fired, deferred) ID lists."""
    from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
        TriggerDeferredResult,
        TriggerMatchResult,
    )

    fired: list[str] = []
    deferred: list[str] = []
    for r in results:
        if isinstance(r, TriggerMatchResult):
            fired.append(r.trigger_id)
        elif isinstance(r, TriggerDeferredResult):
            deferred.append(r.trigger_id)
    return fired, deferred


async def _evaluate_triggers(
    event_type: str,
    action: str,
    payload: dict[str, Any],
    installation_id: str,
) -> tuple[list[str], list[str]]:
    """Evaluate webhook triggers and return (fired, deferred) trigger ID lists."""
    compound_event = f"{event_type}.{action}" if action else event_type
    repository = payload.get("repository", {}).get("full_name", "")

    try:
        from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
            EvaluateWebhookHandler,
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
        return _classify_trigger_results(results)
    except Exception:
        logger.exception("Failed to evaluate webhook triggers")

    return [], []
