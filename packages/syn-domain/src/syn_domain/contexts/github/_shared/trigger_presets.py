"""Built-in trigger presets.

Provides pre-configured trigger rules for common use cases.
"""

from __future__ import annotations

from typing import Any

from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)

SELF_HEALING_PRESET = {
    "name": "self-healing",
    "description": "Auto-fix CI failures on pull requests",
    "event": "check_run.completed",
    "conditions": (
        {"field": "check_run.conclusion", "operator": "eq", "value": "failure"},
        {"field": "check_run.pull_requests", "operator": "not_empty"},
    ),
    "workflow_id": "self-heal-pr",
    "input_mapping": (
        ("repository", "repository.full_name"),
        ("pr_number", "check_run.pull_requests[0].number"),
        ("branch", "check_run.pull_requests[0].head.ref"),
        ("check_name", "check_run.name"),
        ("check_output_title", "check_run.output.title"),
        ("check_output_summary", "check_run.output.summary"),
        ("check_html_url", "check_run.html_url"),
    ),
    "config": (
        ("max_attempts", 3),
        ("budget_per_trigger_usd", 5.00),
        ("daily_limit", 20),
        ("cooldown_seconds", 300),
    ),
}

REVIEW_FIX_PRESET = {
    "name": "review-fix",
    "description": "Auto-fix or respond to review comments on bot-created PRs",
    "event": "pull_request_review.submitted",
    "conditions": (
        {"field": "review.state", "operator": "in", "value": ["changes_requested", "commented"]},
        {"field": "pull_request.draft", "operator": "eq", "value": False},
    ),
    "workflow_id": "self-heal-pr",
    "input_mapping": (
        ("repository", "repository.full_name"),
        ("pr_number", "pull_request.number"),
        ("branch", "pull_request.head.ref"),
        ("review_body", "review.body"),
        ("reviewer", "review.user.login"),
        ("review_html_url", "review.html_url"),
    ),
    "config": (
        ("max_attempts", 2),
        ("budget_per_trigger_usd", 5.00),
        ("daily_limit", 10),
        ("debounce_seconds", 60),
        ("cooldown_seconds", 600),
    ),
}

COMMENT_COMMAND_PRESET = {
    "name": "comment-command",
    "description": "Dispatch a workflow when /syn is used in a PR comment",
    "event": "issue_comment.created",
    "conditions": (
        # Only fire on PR comments (GitHub populates issue.pull_request for PR comments)
        {"field": "issue.pull_request", "operator": "not_empty"},
        # Slash command style — no GitHub @mention ping
        {"field": "comment.body", "operator": "contains", "value": "/syn"},
    ),
    "workflow_id": "self-heal-pr",
    "input_mapping": (
        ("repository", "repository.full_name"),
        ("pr_number", "issue.number"),
        ("pr_title", "issue.title"),
        ("comment_body", "comment.body"),
        ("comment_author", "comment.user.login"),
        ("comment_id", "comment.id"),
        ("comment_html_url", "comment.html_url"),
    ),
    "config": (
        ("max_attempts", 5),
        ("budget_per_trigger_usd", 10.00),
        ("daily_limit", 30),
        ("cooldown_seconds", 60),
    ),
}

PRESETS: dict[str, dict[str, Any]] = {
    "self-healing": SELF_HEALING_PRESET,
    "review-fix": REVIEW_FIX_PRESET,
    "comment-command": COMMENT_COMMAND_PRESET,
}


def create_preset_command(
    preset_name: str,
    repository: str,
    installation_id: str = "",
    created_by: str = "system",
) -> RegisterTriggerCommand:
    """Create a RegisterTriggerCommand from a preset.

    Args:
        preset_name: Name of the preset (self-healing | review-fix).
        repository: Target repository (owner/repo).
        installation_id: GitHub App installation ID.
        created_by: User or agent enabling the preset.

    Returns:
        RegisterTriggerCommand configured from the preset.

    Raises:
        ValueError: If preset_name is not recognized.
    """
    preset = PRESETS.get(preset_name)
    if preset is None:
        raise ValueError(f"Unknown preset: '{preset_name}'. Available: {list(PRESETS.keys())}")

    return RegisterTriggerCommand(
        name=preset["name"],
        event=preset["event"],
        conditions=preset["conditions"],
        repository=repository,
        installation_id=installation_id,
        workflow_id=preset["workflow_id"],
        input_mapping=preset["input_mapping"],
        config=preset["config"],
        created_by=created_by,
    )
