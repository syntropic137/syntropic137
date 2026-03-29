"""Content-based dedup key computation for GitHub events.

Keys are designed to be identical for the same logical event regardless of
whether it arrives via webhook or the Events API. Each event type uses
stable identifiers (commit SHAs, PR numbers, check run IDs) that are
present in both payload formats.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

type _ExtractorFn = Callable[[str, dict[str, Any]], str | None]


def compute_dedup_key(event_type: str, action: str, payload: dict[str, Any]) -> str:
    """Compute a content-based dedup key for a GitHub event.

    The key is deterministic and identical for the same logical event
    whether received via webhook or Events API.
    """
    extractor = _EXTRACTORS.get(event_type)
    if extractor is not None:
        key = extractor(action, payload)
        if key is not None:
            return key

    # Fallback: hash the entire payload for unknown event types.
    # This won't dedup across sources for unknown types — acceptable trade-off.
    return _dedup_fallback(event_type, action, payload)


# ---------------------------------------------------------------------------
# Per-type extractors
# ---------------------------------------------------------------------------


def _dedup_push(action: str, payload: dict[str, Any]) -> str | None:  # noqa: ARG001
    repo = _repo_name(payload)
    after = payload.get("after") or payload.get("head_commit", {}).get("id", "")
    if not after:
        return None
    return f"push:{repo}:{after}"


def _dedup_pull_request(action: str, payload: dict[str, Any]) -> str | None:
    repo = _repo_name(payload)
    pr = payload.get("pull_request", {})
    number = payload.get("number") or pr.get("number", "")
    updated_at = pr.get("updated_at", "")
    return f"pr:{repo}:{number}:{action}:{updated_at}"


def _dedup_check_run(action: str, payload: dict[str, Any]) -> str | None:
    repo = _repo_name(payload)
    check_run_id = payload.get("check_run", {}).get("id", "")
    return f"check_run:{repo}:{check_run_id}:{action}"


def _dedup_check_suite(action: str, payload: dict[str, Any]) -> str | None:
    repo = _repo_name(payload)
    check_suite_id = payload.get("check_suite", {}).get("id", "")
    return f"check_suite:{repo}:{check_suite_id}:{action}"


def _dedup_issue_comment(action: str, payload: dict[str, Any]) -> str | None:
    repo = _repo_name(payload)
    comment_id = payload.get("comment", {}).get("id", "")
    return f"comment:{repo}:{comment_id}:{action}"


def _dedup_pr_review(action: str, payload: dict[str, Any]) -> str | None:
    repo = _repo_name(payload)
    review_id = payload.get("review", {}).get("id", "")
    return f"review:{repo}:{review_id}:{action}"


def _dedup_issues(action: str, payload: dict[str, Any]) -> str | None:
    repo = _repo_name(payload)
    number = payload.get("issue", {}).get("number", "")
    updated_at = payload.get("issue", {}).get("updated_at", "")
    return f"issue:{repo}:{number}:{action}:{updated_at}"


def _dedup_create(action: str, payload: dict[str, Any]) -> str | None:  # noqa: ARG001
    repo = _repo_name(payload)
    ref_type = payload.get("ref_type", "")
    ref = payload.get("ref", "")
    return f"create:{repo}:{ref_type}:{ref}"


def _dedup_delete(action: str, payload: dict[str, Any]) -> str | None:  # noqa: ARG001
    repo = _repo_name(payload)
    ref_type = payload.get("ref_type", "")
    ref = payload.get("ref", "")
    return f"delete:{repo}:{ref_type}:{ref}"


_EXTRACTORS: dict[str, _ExtractorFn] = {
    "push": _dedup_push,
    "pull_request": _dedup_pull_request,
    "check_run": _dedup_check_run,
    "check_suite": _dedup_check_suite,
    "issue_comment": _dedup_issue_comment,
    "pull_request_review": _dedup_pr_review,
    "issues": _dedup_issues,
    "create": _dedup_create,
    "delete": _dedup_delete,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_name(payload: dict[str, Any]) -> str:
    """Extract repository full name from payload (works for both sources)."""
    # Webhook payloads nest under "repository.full_name"
    repo = payload.get("repository", {})
    if isinstance(repo, dict):
        return repo.get("full_name", "")
    # Events API uses "repo.name" at the top level (handled by mapper before
    # dedup key computation, so payload should already be normalized).
    return ""


def _dedup_fallback(event_type: str, action: str, payload: dict[str, Any]) -> str:
    """Hash-based fallback for unknown event types."""
    content = f"{event_type}:{action}:{json.dumps(payload, sort_keys=True, default=str)}"
    return f"unknown:{hashlib.sha256(content.encode()).hexdigest()[:16]}"
