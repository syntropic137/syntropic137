"""Unit tests for InstallationProjection — synced_at stamping and upsert_from_github_api."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from syn_domain.contexts.github.slices.get_installation.projection import (
    InstallationProjection,
)

# ---------------------------------------------------------------------------
# Fake store (mirrors FakeProjectionStore in organization slices conftest)
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal in-memory projection store for unit tests."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return self._data.get(projection, {}).get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection, {}).values())

    async def delete(self, projection: str, key: str) -> None:
        self._data.get(projection, {}).pop(key, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_installed_event(
    installation_id: str = "inst-1",
    account_name: str = "acme-org",
    repos: tuple[str, ...] = ("acme-org/repo-a",),
) -> object:
    from syn_domain.contexts.github.domain.events.AppInstalledEvent import AppInstalledEvent

    return AppInstalledEvent(
        installation_id=installation_id,
        account_id=9001,
        account_name=account_name,
        account_type="Organization",
        repositories=repos,
        permissions={"contents": "write"},
    )


def _make_raw_installation(
    installation_id: str = "inst-1",
    account_login: str = "acme-org",
) -> dict[str, Any]:
    return {
        "id": installation_id,
        "account": {"id": 9001, "login": account_login, "type": "Organization"},
        "permissions": {"contents": "write"},
    }


# ---------------------------------------------------------------------------
# handle_app_installed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_app_installed_sets_synced_at() -> None:
    """handle_app_installed stamps synced_at with the current time."""
    store = _FakeStore()
    proj = InstallationProjection(store=store)
    before = datetime.now(UTC)
    event = _make_installed_event()

    result = await proj.handle_app_installed(event)

    assert result.synced_at is not None
    assert result.synced_at >= before


# ---------------------------------------------------------------------------
# update_repositories
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_repositories_stamps_synced_at() -> None:
    """update_repositories updates synced_at so the cache TTL resets."""
    store = _FakeStore()
    proj = InstallationProjection(store=store)
    event = _make_installed_event(repos=("acme-org/repo-a",))
    await proj.handle_app_installed(event)

    before = datetime.now(UTC)
    result = await proj.update_repositories("inst-1", ["acme-org/repo-b"], [])

    assert result is not None
    assert result.synced_at is not None
    assert result.synced_at >= before


# ---------------------------------------------------------------------------
# upsert_from_github_api
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upsert_from_github_api_new_record() -> None:
    """upsert_from_github_api creates a new projection record with synced_at set."""
    store = _FakeStore()
    proj = InstallationProjection(store=store)
    before = datetime.now(UTC)
    raw = _make_raw_installation()

    result = await proj.upsert_from_github_api(raw)

    assert result.installation_id == "inst-1"
    assert result.account_name == "acme-org"
    assert result.synced_at is not None
    assert result.synced_at >= before
    assert result.repositories == []


@pytest.mark.anyio
async def test_upsert_from_github_api_existing_preserves_repos() -> None:
    """upsert_from_github_api does not overwrite existing repos on the record."""
    store = _FakeStore()
    proj = InstallationProjection(store=store)
    event = _make_installed_event(repos=("acme-org/repo-a", "acme-org/repo-b"))
    await proj.handle_app_installed(event)

    raw = _make_raw_installation()
    result = await proj.upsert_from_github_api(raw)

    assert "acme-org/repo-a" in result.repositories
    assert "acme-org/repo-b" in result.repositories


@pytest.mark.anyio
async def test_upsert_from_github_api_preserves_installed_at() -> None:
    """upsert_from_github_api keeps the original installed_at, not now()."""
    store = _FakeStore()
    proj = InstallationProjection(store=store)
    event = _make_installed_event()
    original = await proj.handle_app_installed(event)

    raw = _make_raw_installation()
    result = await proj.upsert_from_github_api(raw)

    assert result.installed_at == original.installed_at


@pytest.mark.anyio
async def test_upsert_from_github_api_updates_synced_at_on_existing() -> None:
    """upsert_from_github_api always refreshes synced_at, even for existing records."""
    store = _FakeStore()
    proj = InstallationProjection(store=store)
    event = _make_installed_event()
    first = await proj.handle_app_installed(event)

    raw = _make_raw_installation()
    before_second = datetime.now(UTC)
    second = await proj.upsert_from_github_api(raw)

    assert second.synced_at is not None
    assert second.synced_at >= before_second
    assert first.synced_at is not None
    # second call produced an equal or later timestamp
    assert second.synced_at >= first.synced_at


# ---------------------------------------------------------------------------
# Backwards compatibility: synced_at=None is treated as stale by the route
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_all_active_returns_installation_without_synced_at() -> None:
    """Older records without synced_at are returned by get_all_active (not filtered out)."""
    store = _FakeStore()
    proj = InstallationProjection(store=store)
    # Write a record directly without synced_at (simulates pre-migration data)
    await store.save(
        "installations",
        "inst-old",
        {
            "installation_id": "inst-old",
            "account_id": 1,
            "account_name": "legacy-org",
            "account_type": "Organization",
            "status": "active",
            "repositories": [],
            "permissions": {},
            "installed_at": None,
        },
    )

    results = await proj.get_all_active()

    assert len(results) == 1
    assert results[0].installation_id == "inst-old"
    assert results[0].synced_at is None
