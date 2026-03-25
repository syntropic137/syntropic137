"""Unit tests for webhook acknowledgment posting."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from syn_api.routes.webhooks.acknowledgments import (
    _extract_pr_number,
    _post_trigger_acknowledgments,
)

# --- _extract_pr_number ---


def test_extract_pr_number_issue_comment_with_pr() -> None:
    payload = {"issue": {"number": 42, "pull_request": {"url": "..."}}}
    assert _extract_pr_number("issue_comment", payload) == 42


def test_extract_pr_number_issue_comment_without_pr() -> None:
    payload = {"issue": {"number": 42}}
    assert _extract_pr_number("issue_comment", payload) is None


def test_extract_pr_number_check_run() -> None:
    payload = {"check_run": {"pull_requests": [{"number": 7}]}}
    assert _extract_pr_number("check_run", payload) == 7


def test_extract_pr_number_check_run_empty() -> None:
    payload = {"check_run": {"pull_requests": []}}
    assert _extract_pr_number("check_run", payload) is None


def test_extract_pr_number_pull_request() -> None:
    payload = {"pull_request": {"number": 99}}
    assert _extract_pr_number("pull_request", payload) == 99


def test_extract_pr_number_pull_request_review() -> None:
    payload = {"pull_request": {"number": 99}}
    assert _extract_pr_number("pull_request_review", payload) == 99


def test_extract_pr_number_unknown_event() -> None:
    assert _extract_pr_number("deployment", {}) is None


# --- _post_trigger_acknowledgments ---


@pytest.mark.anyio
async def test_post_trigger_acknowledgments_issue_comment_posts_reaction() -> None:
    payload = {
        "repository": {"full_name": "org/repo"},
        "comment": {"id": 123},
        "issue": {"number": 42, "pull_request": {"url": "..."}},
    }
    mock_client = AsyncMock()

    with (
        patch("syn_api.routes.webhooks.acknowledgments.get_github_client", return_value=mock_client, create=True),
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
    ):
        await _post_trigger_acknowledgments(
                event_type="issue_comment",
                payload=payload,
                triggers_fired=["t1"],
                compound_event="issue_comment.created",
                installation_id="inst-1",
            )

    # Should have posted both a reaction and a comment
    assert mock_client.api_post.call_count == 2


@pytest.mark.anyio
async def test_post_trigger_acknowledgments_no_pr_is_noop() -> None:
    payload = {"repository": {"full_name": "org/repo"}}
    mock_client = AsyncMock()

    with patch("syn_adapters.github.client.get_github_client", return_value=mock_client):
        await _post_trigger_acknowledgments(
            event_type="deployment",
            payload=payload,
            triggers_fired=["t1"],
            compound_event="deployment.created",
            installation_id="inst-1",
        )

    mock_client.api_post.assert_not_called()
