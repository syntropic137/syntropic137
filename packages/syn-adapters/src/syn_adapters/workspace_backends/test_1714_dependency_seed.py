"""A platform-warmed dependency seed reaches the workspace's cache, and nothing else does (#1714).

Asserted where the seed is consumed: the files in the host side of
``/workspace/.cache/<tool>`` after the setup phase ran, which is what uv and
pnpm in the container read (`agentic.adapter._WORKSPACE_CACHE_ENV`).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
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
    from contextlib import AbstractContextManager

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
    assert environment["UV_CACHE_DIR"] == "/workspace/.cache/uv"
    # Each spelling separately: pnpm 11+ reads only the first, older pnpm only the second.
    assert environment["pnpm_config_store_dir"] == "/workspace/.cache/pnpm"
    assert environment["npm_config_store_dir"] == "/workspace/.cache/pnpm"


def test_copying_a_seed_keeps_it_from_the_next_prune(tmp_path: Path) -> None:
    store = DependencySeedStore(tmp_path / "seeds", max_bytes=10**9)
    older, newer = SeedKey("uv", "org/app", _sha(_UV_LOCK)), SeedKey("uv", "org/other", "e" * 64)
    store.publish(older, _built_cache(tmp_path / "older", "x" * 100))
    store.publish(newer, _built_cache(tmp_path / "newer", "y" * 100))
    long_ago = time.time() - 7200
    os.utime(tmp_path / "seeds" / older.relative_path, (long_ago, long_ago))
    os.utime(tmp_path / "seeds" / newer.relative_path, (long_ago + 60, long_ago + 60))
    workspace_dir = tmp_path / "ws"
    clone = workspace_dir / "repos" / "app"
    clone.mkdir(parents=True)
    (clone / "uv.lock").write_bytes(_UV_LOCK)

    assert store.seed(workspace_dir, [("org/app", clone)]).copied == [older]
    store._max_bytes = _size_of(tmp_path / "seeds" / older.relative_path)
    store.prune()

    # Copying made the older seed the most recently used, so the other one goes.
    assert (tmp_path / "seeds" / older.relative_path).is_dir()
    assert not (tmp_path / "seeds" / newer.relative_path).exists()


def _size_of(root: Path) -> int:
    return sum(path.lstat().st_size for path in root.rglob("*") if not path.is_dir())


class _FreshCheckout:
    """A workspace nobody has run in, whose tool writes ``built`` into its cache."""

    def __init__(self, root: Path, *, exit_code: int = 0, built: str = "fetched") -> None:
        self.path = root
        self.commands: list[tuple[list[str], str | None]] = []
        #: What each command found in its working directory, and its extra environment.
        self.saw: list[tuple[set[str], dict[str, str]]] = []
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
        assert working_directory is not None
        cwd = self.path / Path(working_directory).relative_to("/workspace")
        self.saw.append(({p.name for p in cwd.iterdir()}, dict(environment or {})))
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
    # Nothing the repository ships may run while a seed is built.
    assert {"--no-build", "--no-install-workspace", "--no-install-local"} <= set(
        dependency_seed.WARM_COMMANDS["uv"]
    )
    assert "--ignore-pnpmfile" in dependency_seed.WARM_COMMANDS["pnpm"]

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


_HOSTILE = {
    ".venv/bin/python": b'#!/bin/sh\necho planted > "$UV_CACHE_DIR/PLANTED"\n',
    "uv.toml": b'cache-dir = "/tmp/elsewhere"\n',
    ".pnpmfile.mjs": b"import fs from 'fs'; fs.writeFileSync('PLANTED', 'x')\n",
    ".npmrc": b"store-dir=/tmp/elsewhere\n",
    ".python-version": b"3.8\n",
}


async def test_a_warm_never_runs_in_the_checkout_or_sees_its_other_files(
    tmp_path: Path, store: DependencySeedStore
) -> None:
    ws = _FreshCheckout(tmp_path / "ws")
    clone = _cloned(
        ws.path,
        {"uv.lock": _UV_LOCK, "pnpm-lock.yaml": b"lockfileVersion: '9.0'\n", "pyproject.toml": b""},
    )
    for name, data in _HOSTILE.items():
        (clone / name).parent.mkdir(parents=True, exist_ok=True)
        (clone / name).write_bytes(data)

    await dependency_seed.seed_dependency_caches(ws, [("org/app", clone)])

    (uv_files, uv_env), (pnpm_files, _) = ws.saw
    assert uv_files == {"uv.lock", "pyproject.toml"}
    assert pnpm_files == {"pnpm-lock.yaml"}
    assert all(not cwd.startswith("/workspace/repos/") for _, cwd in ws.commands)
    uv_cwd = ws.commands[0][1]
    assert uv_env["UV_PROJECT_ENVIRONMENT"] == f"{uv_cwd}/.venv"
    assert uv_env["UV_NO_CONFIG"] == "1"
    # The scratch directories are gone once the warm is done.
    assert not list(ws.path.glob(".seed-warm-*"))


_UV = shutil.which("uv")


@pytest.mark.skipif(_UV is None, reason="needs the uv binary")
async def test_real_uv_does_not_run_a_venv_the_checkout_ships(
    tmp_path: Path, store: DependencySeedStore
) -> None:
    """With the real tool: a checkout's `.venv/bin/python` never runs during a warm."""
    assert _UV is not None
    ws = _LocalWorkspace(tmp_path / "ws")
    clone = ws.path / "repos" / "app"
    clone.mkdir(parents=True)
    (clone / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0"\nrequires-python = ">=3.8"\ndependencies = []\n'
    )
    subprocess.run([_UV, "lock", "--offline", "-q"], cwd=clone, check=True, env=ws.env({}))
    subprocess.run([_UV, "venv", "-q", str(clone / ".venv")], cwd=clone, check=True, env=ws.env({}))
    canary = tmp_path / "CANARY"
    real = (clone / ".venv" / "bin" / "python").resolve()
    (clone / ".venv" / "bin" / "python").unlink()
    (clone / ".venv" / "bin" / "python").write_text(
        f'#!/bin/sh\necho ran > "{canary}"\nexec "{real}" "$@"\n'
    )
    (clone / ".venv" / "bin" / "python").chmod(0o755)

    await dependency_seed.seed_dependency_caches(ws, [("org/app", clone)])

    assert ws.exit_codes == [0]
    assert not canary.exists()


class _LocalWorkspace:
    """A workspace whose commands run on this machine, with `/workspace` mapped to ``root``."""

    def __init__(self, root: Path) -> None:
        self.path = root
        root.mkdir(parents=True)
        self.exit_codes: list[int] = []

    def env(self, extra: dict[str, str]) -> dict[str, str]:
        mapped = {
            name: value.replace("/workspace", str(self.path), 1) for name, value in extra.items()
        }
        return {**os.environ, "UV_CACHE_DIR": str(self.path / ".cache" / "uv"), **mapped}

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        assert working_directory is not None
        cwd = self.path / Path(working_directory).relative_to("/workspace")
        done = subprocess.run(
            [*command, "--offline"] if command[0] == "uv" else command,
            cwd=cwd,
            env=self.env(environment or {}),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        self.exit_codes.append(done.returncode)
        return ExecutionResult(
            exit_code=done.returncode,
            success=done.returncode == 0,
            duration_ms=1.0,
            stderr=done.stderr,
        )


def _aged_store(tmp_path: Path, keys: list[SeedKey], *, max_bytes: int) -> DependencySeedStore:
    """``keys`` published from caches of many files, then last copied two hours ago."""
    store = DependencySeedStore(tmp_path / "seeds", max_bytes=max_bytes)
    long_ago = time.time() - 7200
    for index, key in enumerate(keys):
        built = _built_cache(tmp_path / f"built-{index}", "x" * 100)
        for n in range(20):
            (built / "archive" / f"dep{n}.py").write_text("y" * 100)
        store.publish(key, built)
        os.utime(tmp_path / "seeds" / key.relative_path, (long_ago + index, long_ago + index))
    return store


def _files_under(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if not path.is_dir()}


def _clone_of_uv_lock(tmp_path: Path) -> tuple[Path, Path]:
    workspace_dir = tmp_path / "ws"
    clone = workspace_dir / "repos" / "app"
    clone.mkdir(parents=True)
    (clone / "uv.lock").write_bytes(_UV_LOCK)
    return workspace_dir, clone


def test_a_burst_over_budget_is_pruned_by_cache_hits_alone_once_the_grace_expires(
    tmp_path: Path,
) -> None:
    hit = SeedKey("uv", "org/app", _sha(_UV_LOCK))
    others = [SeedKey("uv", "org/other", "f" * 64), SeedKey("pnpm", "org/other", "0" * 64)]
    store = _aged_store(tmp_path, [*others, hit], max_bytes=10**9)
    seed_bytes = _size_of(tmp_path / "seeds" / hit.relative_path)
    store._max_bytes = seed_bytes
    seeds = [tmp_path / "seeds" / key.relative_path for key in [*others, hit]]
    # The burst: every seed published within the grace, three times the budget.
    for path in seeds:
        os.utime(path)
    assert store.prune() == 0
    assert sum(_size_of(path) for path in seeds if path.exists()) == 3 * seed_bytes

    long_ago = time.time() - 7200
    for path in seeds:
        os.utime(path, (long_ago, long_ago))
    workspace_dir, clone = _clone_of_uv_lock(tmp_path)
    # Only cache hits from here on: nothing is published again.
    assert store.seed(workspace_dir, [("org/app", clone)]).copied == [hit]

    assert sum(_size_of(path) for path in seeds if path.exists()) <= seed_bytes
    assert (tmp_path / "seeds" / hit.relative_path).is_dir()


def test_a_prune_during_a_copy_never_deletes_the_seed_being_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported race: prune snapshots an aged seed, then a copy touches it and starts."""
    key = SeedKey("uv", "org/app", _sha(_UV_LOCK))
    store = _aged_store(tmp_path, [key], max_bytes=1)
    source = tmp_path / "seeds" / key.relative_path
    seed_files = _files_under(source)
    snapshotted, go = threading.Event(), threading.Event()
    pruned: list[int] = []
    real_recorded_size = dependency_seed._recorded_size

    def size_then_pause(seed: Path) -> int:
        size = real_recorded_size(seed)
        if threading.current_thread() is pruner:
            snapshotted.set()  # its stale mtime is taken; hold until the copy is underway
            assert go.wait(10)
        return size

    pruner = threading.Thread(target=lambda: pruned.append(store.prune()))
    monkeypatch.setattr(dependency_seed, "_recorded_size", size_then_pause)

    def copy_pausing_for_the_prune(src: Path, destination: Path) -> None:
        copied = 0

        def copy_one(file_src: str, file_dst: str) -> None:
            nonlocal copied
            shutil.copy2(file_src, file_dst)
            copied += 1
            if copied == 3:  # partway through, let the prune finish
                go.set()
                pruner.join(10)

        shutil.copytree(src, destination, symlinks=True, copy_function=copy_one)

    monkeypatch.setattr(dependency_seed, "_copy_writable", copy_pausing_for_the_prune)
    workspace_dir, clone = _clone_of_uv_lock(tmp_path)
    pruner.start()
    assert snapshotted.wait(10)

    outcome = store.seed(workspace_dir, [("org/app", clone)])
    pruner.join(10)

    assert pruned == [0]
    assert source.is_dir()
    assert outcome.copied == [key]
    assert _files_under(workspace_dir / ".cache" / "uv") == seed_files


def test_a_copy_never_starts_on_a_seed_a_prune_is_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prune has decided under its lease; a copy arriving now waits, then finds no seed."""
    key = SeedKey("uv", "org/app", _sha(_UV_LOCK))
    store = _aged_store(tmp_path, [key], max_bytes=1)
    deleting, go, copy_started = threading.Event(), threading.Event(), threading.Event()
    real_remove = dependency_seed._remove

    def remove_after_a_pause(root: Path) -> None:
        if threading.current_thread() is pruner:
            deleting.set()
            assert go.wait(10)
        real_remove(root)

    def copy_noting_it_started(src: Path, destination: Path) -> None:
        def copy_one(file_src: str, file_dst: str) -> None:
            copy_started.set()
            shutil.copy2(file_src, file_dst)
            pruner.join(10)  # the delete lands while this copy is reading

        shutil.copytree(src, destination, symlinks=True, copy_function=copy_one)

    monkeypatch.setattr(dependency_seed, "_remove", remove_after_a_pause)
    monkeypatch.setattr(dependency_seed, "_copy_writable", copy_noting_it_started)
    pruner = threading.Thread(target=store.prune)
    pruner.start()
    assert deleting.wait(10)
    workspace_dir, clone = _clone_of_uv_lock(tmp_path)
    outcomes: list[SeedOutcome] = []
    seeder = threading.Thread(
        target=lambda: outcomes.append(store.seed(workspace_dir, [("org/app", clone)]))
    )
    seeder.start()

    # Without the lease the copy starts at once; with it, it cannot start at all.
    assert not copy_started.wait(0.5)
    go.set()
    pruner.join(10)
    seeder.join(10)

    assert outcomes[0].missing == [(key, clone)]
    assert outcomes[0].copied == []
    assert not (workspace_dir / ".cache" / "uv").exists()


def test_a_copy_that_breaks_partway_leaves_no_cache_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = SeedKey("uv", "org/app", _sha(_UV_LOCK))
    store = _aged_store(tmp_path, [key], max_bytes=10**9)
    source = tmp_path / "seeds" / key.relative_path
    seed_files = _files_under(source)

    def copy_whose_seed_vanishes(src: Path, destination: Path) -> None:
        copied = 0

        def copy_one(file_src: str, file_dst: str) -> None:
            nonlocal copied
            shutil.copy2(file_src, file_dst)
            copied += 1
            if copied == 3:  # anything that ignores the lease, e.g. an operator's rm
                dependency_seed._remove(src)

        shutil.copytree(src, destination, symlinks=True, copy_function=copy_one)

    monkeypatch.setattr(dependency_seed, "_copy_writable", copy_whose_seed_vanishes)
    workspace_dir, clone = _clone_of_uv_lock(tmp_path)

    outcome = store.seed(workspace_dir, [("org/app", clone)])

    cache = workspace_dir / ".cache" / "uv"
    # Whole or absent, never partial; here the seed is gone, so absent.
    assert not cache.exists() or _files_under(cache) == seed_files
    assert not cache.exists()
    assert outcome.copied == []


def test_prune_skips_a_seed_whose_lease_is_held(tmp_path: Path) -> None:
    key = SeedKey("uv", "org/app", "a" * 64)
    store = _aged_store(tmp_path, [key], max_bytes=1)
    source = tmp_path / "seeds" / key.relative_path

    with dependency_seed._seed_lease(source, exclusive=False):
        assert store.prune() == 0
        assert source.is_dir()
    assert store.prune() > 0
    assert not source.exists()


def test_prune_rereads_the_lru_clock_of_a_seed_copied_after_its_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = SeedKey("uv", "org/app", _sha(_UV_LOCK))
    store = _aged_store(tmp_path, [key], max_bytes=1)
    source = tmp_path / "seeds" / key.relative_path
    workspace_dir, clone = _clone_of_uv_lock(tmp_path)
    real_lease = dependency_seed._seed_lease
    copied_first: list[SeedOutcome] = []

    def lease_after_a_copy(
        seed: Path, *, exclusive: bool, blocking: bool = True
    ) -> AbstractContextManager[None]:
        # Between prune's snapshot and its lease, a whole copy runs and ends.
        if exclusive and not copied_first:
            copied_first.append(store.seed(workspace_dir, [("org/app", clone)]))
        return real_lease(seed, exclusive=exclusive, blocking=blocking)

    monkeypatch.setattr(dependency_seed, "_seed_lease", lease_after_a_copy)

    assert store.prune() == 0
    assert copied_first[0].copied == [key]
    assert source.is_dir()
