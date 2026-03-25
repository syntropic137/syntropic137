"""Unit tests for push commit observability recording."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from syn_api.routes.webhooks.push_events import _build_commit_data, _record_push_commits

# --- _build_commit_data ---


def test_build_commit_data_full_payload() -> None:
    commit = {
        "id": "abc123",
        "message": "fix: resolve bug",
        "author": {"name": "alice"},
        "url": "https://github.com/org/repo/commit/abc123",
        "timestamp": "2026-03-24T12:00:00Z",
    }
    result = _build_commit_data(commit, "org/repo", "main")
    assert result is not None
    assert result["commit_hash"] == "abc123"
    assert result["author"] == "alice"
    assert result["branch"] == "main"
    assert result["repository"] == "org/repo"


def test_build_commit_data_missing_hash_returns_none() -> None:
    assert _build_commit_data({}, "org/repo", "main") is None


def test_build_commit_data_empty_hash_returns_none() -> None:
    assert _build_commit_data({"id": ""}, "org/repo", "main") is None


def test_build_commit_data_defaults() -> None:
    result = _build_commit_data({"id": "abc"}, "org/repo", "main")
    assert result is not None
    assert result["message"] == ""
    assert result["author"] == "unknown"
    assert "github.com/org/repo/commit/abc" in result["url"]


# --- _record_push_commits ---


@pytest.mark.anyio
async def test_record_push_commits_multiple_commits() -> None:
    payload = {
        "commits": [
            {"id": "aaa", "message": "first"},
            {"id": "bbb", "message": "second"},
        ],
        "repository": {"full_name": "org/repo"},
        "ref": "refs/heads/main",
    }
    mock_store = AsyncMock()
    mock_realtime = AsyncMock()

    with (
        patch("syn_api.routes.webhooks.push_events.get_event_store_instance", return_value=mock_store),
        patch("syn_api.routes.webhooks.push_events.get_realtime", return_value=mock_realtime),
    ):
        await _record_push_commits(payload, delivery_id="d1")

    assert mock_store.insert_one.call_count == 2
    assert mock_realtime.broadcast_global.call_count == 2


@pytest.mark.anyio
async def test_record_push_commits_empty_list_noop() -> None:
    payload = {"commits": [], "repository": {"full_name": "org/repo"}, "ref": "refs/heads/main"}
    mock_store = AsyncMock()

    with patch("syn_api.routes.webhooks.push_events.get_event_store_instance", return_value=mock_store):
        await _record_push_commits(payload, delivery_id="d1")

    mock_store.insert_one.assert_not_called()


@pytest.mark.anyio
async def test_record_push_commits_skips_hashless() -> None:
    payload = {
        "commits": [{"id": ""}, {"id": "abc", "message": "good"}],
        "repository": {"full_name": "org/repo"},
        "ref": "refs/heads/main",
    }
    mock_store = AsyncMock()
    mock_realtime = AsyncMock()

    with (
        patch("syn_api.routes.webhooks.push_events.get_event_store_instance", return_value=mock_store),
        patch("syn_api.routes.webhooks.push_events.get_realtime", return_value=mock_realtime),
    ):
        await _record_push_commits(payload, delivery_id="d1")

    assert mock_store.insert_one.call_count == 1


@pytest.mark.anyio
async def test_record_push_commits_extracts_branch_from_ref() -> None:
    payload = {
        "commits": [{"id": "abc"}],
        "repository": {"full_name": "org/repo"},
        "ref": "refs/heads/feature/cool",
    }
    mock_store = AsyncMock()
    mock_realtime = AsyncMock()

    with (
        patch("syn_api.routes.webhooks.push_events.get_event_store_instance", return_value=mock_store),
        patch("syn_api.routes.webhooks.push_events.get_realtime", return_value=mock_realtime),
    ):
        await _record_push_commits(payload, delivery_id="d1")

    call_data = mock_store.insert_one.call_args[0][0]["data"]
    assert call_data["branch"] == "feature/cool"
