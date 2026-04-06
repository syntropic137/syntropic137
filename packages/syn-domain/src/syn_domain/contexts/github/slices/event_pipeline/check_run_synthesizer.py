"""Synthesize check_run.completed NormalizedEvents from Checks API responses (#602).

Pure function — no I/O. Takes a raw check-run dict from the GitHub Checks API
and a PendingSHA context, produces a NormalizedEvent that matches the webhook
``check_run.completed`` payload format exactly. This ensures the existing
``SELF_HEALING_PRESET`` conditions and input mappings work unchanged.

Dedup key: ``check_run:{repo}:{check_run_id}:completed`` — identical to the
key produced for the same check_run delivered via webhook.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA

_FAILURE_CONCLUSIONS: frozenset[str] = frozenset({"failure"})


def synthesize_check_run_event(
    raw_check_run: dict[str, Any],
    pending: PendingSHA,
) -> NormalizedEvent | None:
    """Synthesize a ``check_run.completed`` NormalizedEvent from a Checks API response.

    Returns ``None`` if the check run is not completed, did not fail
    (``conclusion != "failure"``), or is missing a check-run ID.

    Args:
        raw_check_run: A single check-run object from the GitHub Checks API
            response (``GET /repos/{owner}/{repo}/commits/{ref}/check-runs``).
        pending: The PendingSHA context (PR number, branch, repo, etc.).

    Returns:
        A NormalizedEvent matching webhook ``check_run.completed`` format,
        or None if the check run should not trigger self-healing.
    """
    if raw_check_run.get("status") != "completed":
        return None

    conclusion = raw_check_run.get("conclusion", "")
    if conclusion not in _FAILURE_CONCLUSIONS:
        return None

    check_run_id = raw_check_run.get("id")
    if not check_run_id:
        return None

    output = raw_check_run.get("output") or {}

    # Build payload matching webhook check_run.completed format exactly.
    # This satisfies SELF_HEALING_PRESET conditions:
    #   - check_run.conclusion == "failure"  ✓
    #   - check_run.pull_requests not_empty  ✓
    # And all 7 input mappings:
    #   - repository.full_name, check_run.pull_requests[0].number,
    #   - check_run.pull_requests[0].head.ref, check_run.name,
    #   - check_run.output.title, check_run.output.summary, check_run.html_url
    payload: dict[str, Any] = {
        "action": "completed",
        "check_run": {
            "id": check_run_id,
            "name": raw_check_run.get("name", ""),
            "status": "completed",
            "conclusion": conclusion,
            "html_url": raw_check_run.get("html_url", ""),
            "output": {
                "title": output.get("title", ""),
                "summary": output.get("summary", ""),
            },
            "pull_requests": [
                {
                    "number": pending.pr_number,
                    "head": {
                        "ref": pending.branch,
                        "sha": pending.sha,
                    },
                },
            ],
        },
        "repository": {"full_name": pending.repository},
    }

    dedup_key = compute_dedup_key("check_run", "completed", payload)

    return NormalizedEvent(
        event_type="check_run",
        action="completed",
        repository=pending.repository,
        installation_id=pending.installation_id,
        dedup_key=dedup_key,
        source=EventSource.CHECKS_API,
        payload=payload,
        received_at=datetime.now(UTC),
    )
