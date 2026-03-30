"""PR comment, reaction, and trigger-started acknowledgment posting."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Trigger name labels for human-readable status comments
_TRIGGER_LABELS: dict[str, str] = {
    "check_run.completed": "Self-Heal",
    "pull_request_review.submitted": "Review Fix",
    "issue_comment.created": "Command",
}


async def _resolve_trigger_details(
    trigger_ids: list[str],
) -> list[dict[str, str]]:
    """Look up trigger name and workflow name for each trigger ID (best-effort).

    Returns a list of dicts with keys: trigger_id, trigger_name, workflow_name.
    Falls back to raw IDs on any failure.
    """
    details: list[dict[str, str]] = []
    try:
        from syn_api._wiring import get_trigger_store

        store = get_trigger_store()
        for tid in trigger_ids:
            entry: dict[str, str] = {"trigger_id": tid, "trigger_name": "", "workflow_name": ""}
            trigger = await store.get(tid)
            if trigger is not None:
                entry["trigger_name"] = trigger.name
                entry["workflow_id"] = trigger.workflow_id
            details.append(entry)

        # Batch-resolve workflow names from projection store
        workflow_ids = {d["workflow_id"] for d in details if d.get("workflow_id")}
        if workflow_ids:
            from syn_adapters.projection_stores import get_projection_store

            proj_store = get_projection_store()
            for wf_id in workflow_ids:
                try:
                    data = await proj_store.get("workflow_details", wf_id)
                    if data:
                        wf_name = data.get("name", "")
                        for d in details:
                            if d.get("workflow_id") == wf_id:
                                d["workflow_name"] = wf_name
                except Exception:
                    pass
    except Exception:
        logger.debug("Could not resolve trigger details for acknowledgment", exc_info=True)
        details = [
            {"trigger_id": tid, "trigger_name": "", "workflow_name": ""} for tid in trigger_ids
        ]
    return details


# Dispatch table for extracting PR numbers from webhook payloads
_PR_EXTRACTORS: dict[str, Any] = {
    "issue_comment": lambda p: p.get("issue", {}).get("number")
    if p.get("issue", {}).get("pull_request")
    else None,
    "check_run": lambda p: prs[0].get("number")
    if (prs := p.get("check_run", {}).get("pull_requests", []))
    else None,
    "pull_request_review": lambda p: p.get("pull_request", {}).get("number"),
    "pull_request": lambda p: p.get("pull_request", {}).get("number"),
}


def _extract_pr_number(event_type: str, payload: dict[str, Any]) -> int | None:
    """Extract the PR number from a webhook payload (best-effort)."""
    extractor = _PR_EXTRACTORS.get(event_type)
    return extractor(payload) if extractor else None


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
    details = await _resolve_trigger_details(trigger_ids)

    body = f"⚡ **{label} Starting**\n\n"
    for d in details:
        name = d.get("trigger_name") or d["trigger_id"]
        workflow = d.get("workflow_name")
        if workflow:
            body += (
                f"Trigger **{name}** fired on `{compound_event}` — dispatching **{workflow}**.\n"
            )
        else:
            body += f"Trigger **{name}** fired on `{compound_event}` — dispatching workflow.\n"

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
