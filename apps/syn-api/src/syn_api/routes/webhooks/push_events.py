"""Push commit observability recording (Lane 2 — telemetry only)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from syn_api._wiring import get_event_store_instance, get_realtime

logger = logging.getLogger(__name__)


def _build_commit_data(commit: dict[str, Any], repo: str, branch: str) -> dict[str, Any] | None:
    """Build observability data dict for a single commit, or None if no hash."""
    commit_hash: str = commit.get("id", "")
    if not commit_hash:
        return None
    return {
        "commit_hash": commit_hash,
        "message": commit.get("message", ""),
        "author": commit.get("author", {}).get("name", "unknown"),
        "repository": repo,
        "branch": branch,
        "url": commit.get("url", f"https://github.com/{repo}/commit/{commit_hash}"),
        "timestamp": commit.get("timestamp", datetime.now(UTC).isoformat()),
    }


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
        data = _build_commit_data(commit, repo, branch)
        if data is None:
            continue

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
            extra={"commit_hash": data["commit_hash"][:7], "repo": repo, "branch": branch},
        )
