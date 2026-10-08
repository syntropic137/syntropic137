"""Independent data-loss regressions for production Git and filesystem shapes."""

from __future__ import annotations

import io
import os
import tarfile
from typing import TYPE_CHECKING

import pytest
from test_pc130_workspace_dir_reclaim import _Archive, _git, _reclaimer, _workspace

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration import StaleWorkspaceDir

pytestmark = pytest.mark.unit


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
async def test_git_index_flags_cannot_hide_the_only_copy(
    base: Path, tmp_path: Path, flag: str
) -> None:
    ws = _workspace(base, "ws-hidden", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "update-index", flag, "README.md")
    (app / "README.md").write_bytes(b"authored content hidden by Git's index\n")
    archive = _Archive()
    result = await _reclaimer(base, archive=archive).run_once()
    # These flags make Git's patch incomplete, so retain the source directory.
    assert result.kept == ("ws-hidden",)
    assert (app / "README.md").read_bytes() == b"authored content hidden by Git's index\n"


async def test_package_manifest_does_not_prove_dependency_files_regenerable(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-authored-dependency", tmp_path)
    app = ws / "repos" / "app"
    (app / "package.json").write_text('{"dependencies": {}}\n')
    (app / ".git" / "info" / "exclude").write_text("node_modules/\n")
    authored = app / "node_modules" / "local" / "only-copy.js"
    authored.parent.mkdir(parents=True)
    authored.write_bytes(b"module.exports = 'authored, not installable';\n")
    archive = _Archive()
    result = await _reclaimer(base, archive=archive).run_once()
    assert result.reclaimed == ("ws-authored-dependency",)
    [tarball] = archive.files
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        member = tar.extractfile("repos/app/node_modules/local/only-copy.js")
        assert member is not None
        assert member.read() == b"module.exports = 'authored, not installable';\n"


async def test_timestamp_preserving_write_during_upload_keeps_new_content(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-preserved-time", tmp_path)
    notes = ws / "notes.md"
    notes.write_bytes(b"before upload\n")
    original = notes.stat()

    class ChangesDuringUpload(_Archive):
        async def save_files(self, stale: StaleWorkspaceDir, tarball: bytes) -> str:
            notes.write_bytes(b"after upload, only copy\n")
            os.utime(notes, ns=(original.st_atime_ns, original.st_mtime_ns))
            return await super().save_files(stale, tarball)

    result = await _reclaimer(base, archive=ChangesDuringUpload()).run_once()
    assert result.kept == ("ws-preserved-time",)
    assert notes.read_bytes() == b"after upload, only copy\n"


async def test_production_reclaimer_reads_the_registered_ownership_store(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_adapters import projection_stores
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_api.services.workspace_dir_reclaim import default_reclaimer
    from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
        WorkspaceOwnershipProjection,
    )
    from syn_domain.contexts.orchestration.slices.workspace_ownership.value_objects import (
        WorkspaceOwner,
    )

    ws = _workspace(base, "ws-production-wiring", tmp_path)
    (ws / "repos" / "app" / "README.md").write_text("production lookup\n")
    store = InMemoryProjectionStore()
    await store.save(
        WorkspaceOwnershipProjection.PROJECTION_NAME,
        ws.name,
        WorkspaceOwner(workspace_id=ws.name, execution_ids=("exec-durable",)).model_dump(
            mode="json"
        ),
    )
    monkeypatch.setattr(projection_stores, "get_projection_store", lambda: store)
    reclaimer = default_reclaimer(lambda: True)
    infrastructure = _reclaimer(base)
    reclaimer.base_dir = str(base)
    reclaimer.clock = infrastructure.clock
    reclaimer.list_containers = infrastructure.list_containers
    reclaimer.running_execution_ids = infrastructure.running_execution_ids
    archive = _Archive()
    reclaimer.archive = archive
    result = await reclaimer.run_once()
    assert result.reclaimed == (ws.name,)
    assert [owner for owner, _ in archive.saved] == ["exec-durable"]


async def test_unreadable_owner_index_skips_reclaim(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-unreadable-owner", tmp_path)
    reclaimer = _reclaimer(base)

    async def unreadable(workspace_id: str) -> set[str]:
        raise OSError("ownership database unavailable")

    reclaimer.workspace_owners = unreadable
    result = await reclaimer.run_once()
    assert result.skipped is not None
    assert ws.exists()


async def test_conflicting_durable_owners_protect_the_directory(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-conflicting-owners", tmp_path)
    reclaimer = _reclaimer(base)

    async def owners(workspace_id: str) -> set[str]:
        return {"exec-first", "exec-second"}

    reclaimer.workspace_owners = owners
    result = await reclaimer.run_once()
    assert result.reclaimed == ()
    assert ws.exists()
