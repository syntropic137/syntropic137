"""Map GitHub Events API responses to NormalizedEvent instances (ISS-386).

The Events API uses different type naming (e.g. ``PushEvent`` vs webhook
``push``). This mapper bridges that gap and produces ``NormalizedEvent``
instances ready for pipeline ingestion.

The type map is derived from ``event_availability.py`` — the single source
of truth for which events are available via which delivery channel (ISS-409).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from syn_domain.contexts.github._shared.event_availability import build_events_api_type_map
from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)

logger = logging.getLogger(__name__)

# Maps Events API type names (e.g. "PushEvent") to webhook names (e.g. "push").
# Derived from event_availability.py — only includes events actually returned
# by the Events API (no dead entries for webhook-only types like CheckRunEvent).
# https://docs.github.com/en/rest/using-the-rest-api/github-event-types
_EVENTS_API_TYPE_MAP: dict[str, str] = build_events_api_type_map()

# Maps Events API action names to webhook action names for events where they differ.
# GitHub's Events API uses different action values than webhooks for some event types.
# Only PullRequestReviewEvent has known mismatches — all other events use matching actions.
# See: https://docs.github.com/en/rest/using-the-rest-api/github-event-types
_EVENTS_API_ACTION_MAP: dict[str, dict[str, str]] = {
    "pull_request_review": {"created": "submitted", "updated": "edited"},
}


def map_events_api_to_normalized(
    raw_event: dict[str, Any],
    installation_id: str,
) -> NormalizedEvent | None:
    """Map a single Events API item to a ``NormalizedEvent``.

    Returns ``None`` for unmapped event types (silently skipped by the poller).

    The Events API ``payload`` field has the same structure as a webhook
    payload body (minus the top-level ``installation``, ``repository``,
    ``sender`` wrappers). The mapper reconstructs ``repository.full_name``
    from the Events API ``repo.name`` field so that dedup keys are consistent.
    """
    api_type = raw_event.get("type", "")
    event_type = _EVENTS_API_TYPE_MAP.get(api_type)
    if event_type is None:
        logger.debug("Unmapped Events API type: %s", api_type)
        return None

    payload: dict[str, Any] = raw_event.get("payload", {})
    action: str = str(payload.get("action", ""))

    # Normalize action names that differ between Events API and webhooks
    action_map = _EVENTS_API_ACTION_MAP.get(event_type)
    if action_map:
        action = action_map.get(action, action)

    # Events API uses "repo.name" which is "owner/repo" format
    repo_name = raw_event.get("repo", {}).get("name", "")
    event_id = str(raw_event.get("id", ""))
    created_at = raw_event.get("created_at", "")

    # Inject repository info into payload so dedup key extractors
    # and trigger conditions can resolve "repository.full_name".
    enriched_payload = {
        **payload,
        "repository": {"full_name": repo_name},
    }

    dedup_key = compute_dedup_key(event_type, action, enriched_payload)

    if created_at and created_at.endswith("Z"):
        created_at = created_at[:-1] + "+00:00"
    received_at = datetime.fromisoformat(created_at) if created_at else datetime.now(UTC)

    return NormalizedEvent(
        event_type=event_type,
        action=action,
        repository=repo_name,
        installation_id=installation_id,
        dedup_key=dedup_key,
        source=EventSource.EVENTS_API,
        payload=enriched_payload,
        received_at=received_at,
        events_api_id=event_id,
    )
