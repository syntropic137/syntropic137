"""Independent data-loss regressions for production Git and filesystem shapes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from test_pc130_workspace_dir_reclaim import _git, _reason, _reclaimer, _workspace

from syn_domain.contexts.orchestration import OwnerExecution, RetainedReason

if TYPE_CHECKING:
    from pathlib import Path

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
    result = await _reclaimer(base).run_once()
    # These flags make Git's own answer incomplete, so the directory stays.
    assert _reason(result, "ws-hidden") is RetainedReason.UNREADABLE
    assert (app / "README.md").read_bytes() == b"authored content hidden by Git's index\n"


async def test_package_manifest_does_not_prove_dependency_files_regenerable(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-authored-dependency", tmp_path)
    app = ws / "repos" / "app"
    (app / "package.json").write_text('{"dependencies": {}}\n')
    (app / ".git" / "info" / "exclude").write_text("node_modules/\npackage.json\n")
    authored = app / "node_modules" / "local" / "only-copy.js"
    authored.parent.mkdir(parents=True)
    authored.write_bytes(b"module.exports = 'authored, not installable';\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-authored-dependency") is RetainedReason.UNVERSIONED
    assert authored.read_bytes() == b"module.exports = 'authored, not installable';\n"


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
    reclaimer.host_base_dir = infrastructure.host_base_dir
    reclaimer.own_container = infrastructure.own_container
    reclaimer.list_containers = infrastructure.list_containers
    reclaimer.capture_unproven = infrastructure.capture_unproven
    reclaimer.read_models_rebuilding = infrastructure.read_models_rebuilding
    reclaimer.paused = infrastructure.paused
    asked: list[str] = []

    async def execution_record(execution_id: str) -> OwnerExecution | None:
        asked.append(execution_id)
        record = await infrastructure.execution_record(f"exec-{ws.name}")
        assert record is not None
        return OwnerExecution(execution_id, record.status, record.terminal_at, record.repositories)

    reclaimer.execution_record = execution_record
    result = await reclaimer.run_once()
    assert result.reclaimed == (ws.name,)
    assert asked == ["exec-durable", "exec-durable"]  # judged, then judged again under the claim


async def test_unreadable_owner_index_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-unreadable-owner", tmp_path)
    reclaimer = _reclaimer(base)

    async def unreadable(workspace_id: str) -> set[str]:
        raise OSError("ownership database unavailable")

    reclaimer.workspace_owners = unreadable
    result = await reclaimer.run_once()
    assert _reason(result, "ws-unreadable-owner") is RetainedReason.UNOWNED
    assert "ownership unreadable" in result.retained[0].detail
    assert ws.exists()


async def test_unreadable_execution_record_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-unreadable-record", tmp_path)
    reclaimer = _reclaimer(base)

    async def unreadable(execution_id: str) -> OwnerExecution | None:
        raise OSError("projection store unavailable")

    reclaimer.execution_record = unreadable
    result = await reclaimer.run_once()
    assert _reason(result, "ws-unreadable-record") is RetainedReason.NOT_TERMINAL
    assert ws.exists()
