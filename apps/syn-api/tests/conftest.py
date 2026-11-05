"""Shared fixtures for the syn-api tests."""

from __future__ import annotations

import pytest

from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskThresholds, DiskUsage


class _RoomyDisk:
    """A workspace volume with plenty of room, so no test reads the real disk."""

    @property
    def path(self) -> str:
        return "/workspaces"

    def usage(self) -> DiskUsage:
        return DiskUsage(free_bytes=900, total_bytes=1000)


@pytest.fixture(autouse=True)
def _roomy_workspace_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this, /health and admission measure the host's real disk (#1560).

    A test machine without the workspace mount reads as unmeasurable and every
    /health assertion of ``mode == "full"`` would fail for a reason unrelated
    to it. Tests about disk space replace this guard with their own.
    """
    guard = DiskSpaceGuard(
        _RoomyDisk(),
        DiskThresholds(
            refuse_admission_below_bytes=0,
            degraded_below_bytes=0,
            refuse_basis="test",
            refuse_admission_below_percent=5.0,
            degraded_below_percent=10.0,
        ),
    )
    monkeypatch.setattr("syn_api._wiring_admission.get_disk_space_guard", lambda: guard)


@pytest.fixture(autouse=True)
def _fresh_repo_listing_cache() -> None:
    """Each test starts with no cached `/github/repos` listing."""
    from syn_api.services.github_repo_listing_cache import reset_repo_listing_cache

    reset_repo_listing_cache()


@pytest.fixture(autouse=True)
def _fresh_workspace_memory_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test sizes the process ledger from its own settings.

    It is a process singleton sized on first use, so without this a test that
    sets ``SYN_WORKSPACE_MEMORY_LIMIT_MB`` leaves a ledger of that size for
    whichever test the worker runs next.
    """
    monkeypatch.setattr("syn_api._wiring_workspace_memory._ledger_singleton", None)
