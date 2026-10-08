"""A platform-warmed dependency seed reaches the workspace's cache, and nothing else does (#1714).

Asserted where the seed is consumed: the files in the host side of
``/workspace/.cache/<tool>`` after the setup phase ran, which is what uv and
pnpm in the container read (`agentic.adapter._WORKSPACE_CACHE_ENV`).
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from syn_adapters.workspace_backends import dependency_seed
from syn_adapters.workspace_backends.agentic.adapter import _with_executable_tmpdir
from syn_adapters.workspace_backends.dependency_seed import (
    DependencySeedStore,
    SeedKey,
    SeedOutcome,
)
from syn_adapters.workspace_backends.service import managed_workspace
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

if TYPE_CHECKING:
    from pathlib import Path

    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService

pytestmark = pytest.mark.unit

_REPO = "https://github.com/org/app"
_UV_LOCK = b'version = 1\n[[package]]\nname = "seeded"\n'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _built_cache(root: Path, marker: str) -> Path:
    """A cache the platform built: one wheel-ish file, one executable, one symlink."""
    root.mkdir(parents=True)
    (root / "archive").mkdir()
    (root / "archive" / "pkg.py").write_text(marker)
    (root / "archive" / "tool").write_text("#!/bin/sh\n")
    (root / "archive" / "tool").chmod(0o755)
    (root / "link").symlink_to("archive/pkg.py")
    return root


async def _setup_phase_cloning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, bytes]
) -> Path:
    """Run `ManagedWorkspace.run_setup_phase` with a setup script that clones ``files``."""
    workspace_dir = tmp_path / "ws"
    clone = workspace_dir / "repos" / "app"

    async def clone_then_succeed(*_args: object) -> ExecutionResult:
        clone.mkdir(parents=True)
        for name, data in files.items():
            (clone / name).write_bytes(data)
        return ExecutionResult(exit_code=0, success=True, duration_ms=1.0)

    monkeypatch.setattr(managed_workspace, "_run_setup_phase", clone_then_succeed)
    handle = MagicMock()
    handle.host_workspace_path = str(workspace_dir)
    ws = ManagedWorkspace(
        workspace_id="ws-1714",
        execution_id="exec-1714",
        aggregate=MagicMock(),
        isolation_handle=handle,
        sidecar_handle=None,
        _service=cast("WorkspaceService", MagicMock()),
    )
    await ws.run_setup_phase(SetupPhaseSecrets.for_testing(repositories=[_REPO]))
    return workspace_dir


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DependencySeedStore:
    seeds = DependencySeedStore(tmp_path / "seeds", max_bytes=10**9)
    monkeypatch.setattr(dependency_seed, "configured_store", lambda: seeds)
    return seeds


async def test_the_setup_phase_copies_the_seed_for_the_cloned_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: DependencySeedStore
) -> None:
    store.publish(
        SeedKey("uv", "org/app", _sha(_UV_LOCK)), _built_cache(tmp_path / "built", "warm")
    )

    workspace_dir = await _setup_phase_cloning(tmp_path, monkeypatch, {"uv.lock": _UV_LOCK})

    cache = workspace_dir / ".cache" / "uv"
    assert (cache / "archive" / "pkg.py").read_text() == "warm"
    assert (cache / "link").is_symlink()
    assert os.access(cache / "archive" / "tool", os.X_OK)


async def test_a_changed_lockfile_never_reuses_the_old_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: DependencySeedStore
) -> None:
    store.publish(
        SeedKey("uv", "org/app", _sha(_UV_LOCK)), _built_cache(tmp_path / "built", "stale")
    )

    workspace_dir = await _setup_phase_cloning(
        tmp_path, monkeypatch, {"uv.lock": _UV_LOCK + b"# one more line\n"}
    )

    assert not (workspace_dir / ".cache" / "uv" / "archive" / "pkg.py").exists()


async def test_the_workspace_writes_its_copy_and_never_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: DependencySeedStore
) -> None:
    key = SeedKey("uv", "org/app", _sha(_UV_LOCK))
    store.publish(key, _built_cache(tmp_path / "built", "warm"))

    workspace_dir = await _setup_phase_cloning(tmp_path, monkeypatch, {"uv.lock": _UV_LOCK})
    (workspace_dir / ".cache" / "uv" / "archive" / "pkg.py").write_text("poisoned")
    (workspace_dir / ".cache" / "uv" / "archive" / "new.whl").write_text("planted")

    seed = tmp_path / "seeds" / key.relative_path
    assert (seed / "archive" / "pkg.py").read_text() == "warm"
    assert not (seed / "archive" / "new.whl").exists()
    # And the published seed itself is not writable on disk.
    assert not os.access(seed / "archive" / "pkg.py", os.W_OK) or os.geteuid() == 0
    assert not (seed / "archive").stat().st_mode & 0o222


async def test_a_symlinked_lockfile_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: DependencySeedStore
) -> None:
    secret = tmp_path / "host-secret"
    secret.write_bytes(_UV_LOCK)
    store.publish(
        SeedKey("uv", "org/app", _sha(_UV_LOCK)), _built_cache(tmp_path / "built", "warm")
    )
    workspace_dir = tmp_path / "ws"
    (workspace_dir / "repos" / "app").mkdir(parents=True)
    (workspace_dir / "repos" / "app" / "uv.lock").symlink_to(secret)

    outcome = store.seed(workspace_dir, [("org/app", workspace_dir / "repos" / "app")])

    assert outcome == SeedOutcome()


async def test_no_store_configured_leaves_the_workspace_cold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dependency_seed, "configured_store", lambda: None)

    workspace_dir = await _setup_phase_cloning(tmp_path, monkeypatch, {"uv.lock": _UV_LOCK})

    assert not (workspace_dir / ".cache").exists()


def test_prune_drops_the_least_recently_copied_seed_past_the_budget(tmp_path: Path) -> None:
    store = DependencySeedStore(tmp_path / "seeds", max_bytes=1)
    old, new = SeedKey("uv", "org/app", "a" * 64), SeedKey("pnpm", "org/app", "b" * 64)
    store.publish(old, _built_cache(tmp_path / "old", "x" * 100))
    store.publish(new, _built_cache(tmp_path / "new", "y" * 100))
    long_ago = time.time() - 7200
    os.utime(tmp_path / "seeds" / old.relative_path, (long_ago, long_ago))
    os.utime(tmp_path / "seeds" / new.relative_path, (long_ago + 60, long_ago + 60))

    freed = store.prune()

    assert freed > 0
    assert not (tmp_path / "seeds" / old.relative_path).exists()
    # Still over a 1-byte budget, so the newer one goes too; LRU order is the point.
    assert not (tmp_path / "seeds" / new.relative_path).exists()


def test_prune_never_deletes_a_seed_copied_within_the_grace(tmp_path: Path) -> None:
    store = DependencySeedStore(tmp_path / "seeds", max_bytes=1)
    key = SeedKey("uv", "org/app", "c" * 64)
    built = _built_cache(tmp_path / "b", "z" * 100)
    # A cache built long ago is still a seed published just now.
    long_ago = time.time() - 7200
    os.utime(built, (long_ago, long_ago))
    store.publish(key, built)

    assert store.prune() == 0
    assert (tmp_path / "seeds" / key.relative_path).is_dir()


def test_a_repository_that_names_a_directory_outside_the_store_is_refused() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        SeedKey("uv", "../etc", "d" * 64)


def test_pnpm_is_pointed_at_the_cache_a_seed_is_copied_into() -> None:
    environment = _with_executable_tmpdir({})
    for tool in dependency_seed.SEEDED_TOOLS:
        assert f"/workspace/.cache/{tool}" in environment.values()


class _FreshCheckout:
    """A workspace nobody has run in, whose tool writes ``built`` into its cache."""

    def __init__(self, root: Path, *, exit_code: int = 0, built: str = "fetched") -> None:
        self.path = root
        self.commands: list[tuple[list[str], str | None]] = []
        self._exit_code = exit_code
        self._built = built

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        self.commands.append((command, working_directory))
        cache = self.path / ".cache" / command[0]
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "pkg").write_text(self._built)
        return ExecutionResult(
            exit_code=self._exit_code, success=self._exit_code == 0, duration_ms=1.0
        )


def _cloned(root: Path, files: dict[str, bytes]) -> Path:
    clone = root / "repos" / "app"
    clone.mkdir(parents=True)
    for name, data in files.items():
        (clone / name).write_bytes(data)
    return clone


async def test_a_missing_seed_is_warmed_by_a_download_only_command_and_served_next_time(
    tmp_path: Path, store: DependencySeedStore
) -> None:
    pnpm_lock = b"lockfileVersion: '9.0'\n"
    first = _FreshCheckout(tmp_path / "first")
    clone = _cloned(first.path, {"uv.lock": _UV_LOCK, "pnpm-lock.yaml": pnpm_lock})

    await dependency_seed.seed_dependency_caches(first, [("org/app", clone)])

    assert [command for command, _ in first.commands] == [
        list(dependency_seed.WARM_COMMANDS["uv"]),
        list(dependency_seed.WARM_COMMANDS["pnpm"]),
    ]
    assert {cwd for _, cwd in first.commands} == {"/workspace/repos/app"}
    # Nothing the repository ships may run while a seed is built.
    assert {"--no-build", "--no-install-workspace", "--no-install-local"} <= set(
        dependency_seed.WARM_COMMANDS["uv"]
    )

    second = _FreshCheckout(tmp_path / "second")
    clone = _cloned(second.path, {"uv.lock": _UV_LOCK, "pnpm-lock.yaml": pnpm_lock})
    await dependency_seed.seed_dependency_caches(second, [("org/app", clone)])

    assert second.commands == []
    assert (second.path / ".cache" / "uv" / "pkg").read_text() == "fetched"
    assert (second.path / ".cache" / "pnpm" / "pkg").read_text() == "fetched"


async def test_a_warm_that_fails_publishes_nothing(
    tmp_path: Path, store: DependencySeedStore
) -> None:
    ws = _FreshCheckout(tmp_path / "ws", exit_code=1, built="half")
    clone = _cloned(ws.path, {"uv.lock": _UV_LOCK})

    await dependency_seed.seed_dependency_caches(ws, [("org/app", clone)])

    assert not (
        tmp_path / "seeds" / SeedKey("uv", "org/app", _sha(_UV_LOCK)).relative_path
    ).exists()
