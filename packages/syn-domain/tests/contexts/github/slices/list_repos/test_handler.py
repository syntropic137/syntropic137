"""Tests for ListAccessibleReposHandler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.github.domain.queries.list_accessible_repos import (
    ListAccessibleReposQuery,
)
from syn_domain.contexts.github.slices.list_repos.handler import (
    ListAccessibleReposHandler,
)


def _make_repo(idx: int, *, private: bool = False, default_branch: str = "main") -> dict:
    """Create a raw GitHub API repo dict."""
    return {
        "id": idx,
        "name": f"repo-{idx}",
        "full_name": f"org/repo-{idx}",
        "private": private,
        "default_branch": default_branch,
    }


def _make_client(repos: list[dict]) -> MagicMock:
    """Create a mock client returning the given repos."""
    client = MagicMock()
    client.list_accessible_repos = AsyncMock(return_value=repos)
    return client


@pytest.mark.asyncio
async def test_maps_raw_dicts_to_read_models() -> None:
    """Raw GitHub dicts are mapped to AccessibleRepository correctly."""
    raw = [_make_repo(1), _make_repo(2, private=True, default_branch="develop")]
    client = _make_client(raw)
    handler = ListAccessibleReposHandler(client)

    query = ListAccessibleReposQuery(installation_id="inst-42")
    result = await handler.handle(query)

    assert len(result) == 2
    assert result[0].id == 1
    assert result[0].full_name == "org/repo-1"
    assert result[0].installation_id == "inst-42"
    assert result[1].private is True
    assert result[1].default_branch == "develop"


@pytest.mark.asyncio
async def test_filters_private_repos() -> None:
    """include_private=False excludes private repos."""
    raw = [_make_repo(1), _make_repo(2, private=True), _make_repo(3)]
    client = _make_client(raw)
    handler = ListAccessibleReposHandler(client)

    query = ListAccessibleReposQuery(installation_id="inst-1", include_private=False)
    result = await handler.handle(query)

    assert len(result) == 2
    assert all(not r.private for r in result)


@pytest.mark.asyncio
async def test_skips_malformed_entries() -> None:
    """Entries missing required fields are skipped."""
    raw = [
        _make_repo(1),
        {"id": 2},  # missing name and full_name
        {"name": "no-id"},  # missing id and full_name
        _make_repo(4),
    ]
    client = _make_client(raw)
    handler = ListAccessibleReposHandler(client)

    query = ListAccessibleReposQuery(installation_id="inst-1")
    result = await handler.handle(query)

    assert len(result) == 2
    assert result[0].id == 1
    assert result[1].id == 4


@pytest.mark.asyncio
async def test_empty_list() -> None:
    """Empty list from client returns empty list."""
    client = _make_client([])
    handler = ListAccessibleReposHandler(client)

    query = ListAccessibleReposQuery(installation_id="inst-1")
    result = await handler.handle(query)

    assert result == []
