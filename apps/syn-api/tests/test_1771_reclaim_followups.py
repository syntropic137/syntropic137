"""#1771: the guards PR #1755's verification found unkilled, and the ways a
directory could stay claimed or a pass could trust a stale or emptied input."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from test_pc130_workspace_dir_reclaim import _git, _reclaimer, _workspace

from syn_adapters.subscriptions.read_model_lag import ProjectionLag, ReadModelLag
from syn_adapters.workspace_backends import stale_dirs
from syn_adapters.workspace_backends.stale_dirs import CLAIM_PREFIX, WorkspaceContainer
from syn_api.services import lifecycle, workspace_dir_reclaim
from syn_api.services.read_model_status import read_models_rebuilding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


# -- 1a: a container docker cannot inspect is not "a container with no mount" --


class _DockerPs:
    returncode = 0

    async def communicate(self) -> tuple[bytes, None]:
        return b"cafe01\n", None


async def _docker_ps(*_args: object, **_kwargs: object) -> _DockerPs:
    return _DockerPs()


async def _uninspectable(container_id: str) -> None:
    return None


async def test_an_uninspectable_container_skips_the_pass_and_keeps_the_dir(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(base, "ws-uninspectable", tmp_path)
    monkeypatch.setattr(stale_dirs.asyncio, "create_subprocess_exec", _docker_ps)
    monkeypatch.setattr(stale_dirs, "docker_inspect_raw", _uninspectable)
    reclaimer = _reclaimer(base)
    reclaimer.list_containers = stale_dirs.list_workspace_containers
    result = await reclaimer.run_once()
    assert result.skipped is not None
    assert "could not inspect workspace container cafe01" in result.skipped
    assert ws.exists()


# -- 1b: a truncated running-execution list is no list at all --


def _execution_list(count: int, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [SimpleNamespace(workflow_execution_id=f"exec-{i}") for i in range(count)]

    async def get_all(**_kwargs: object) -> list[SimpleNamespace]:
        return rows

    manager = SimpleNamespace(workflow_execution_list=SimpleNamespace(get_all=get_all))
    monkeypatch.setattr("syn_api._wiring.get_projection_mgr", lambda: manager)


async def test_a_full_page_of_running_executions_skips_the_pass(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(base, "ws-truncated", tmp_path)
    # The page is full, and its owner is the execution the page left out.
    _execution_list(workspace_dir_reclaim._MAX_RUNNING_EXECUTIONS, monkeypatch)
    reclaimer = _reclaimer(base)
    reclaimer.running_execution_ids = workspace_dir_reclaim._running_execution_ids

    async def owned_by_one_more(workspace_id: str) -> set[str]:
        return {"exec-not-on-the-page"}

    reclaimer.workspace_owners = owned_by_one_more
    result = await reclaimer.run_once()
    assert result.skipped is not None
    assert "may be truncated" in result.skipped
    assert ws.exists()


async def test_one_short_of_a_full_page_is_read_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    _execution_list(workspace_dir_reclaim._MAX_RUNNING_EXECUTIONS - 1, monkeypatch)
    running = await workspace_dir_reclaim._running_execution_ids()
    assert len(running) == workspace_dir_reclaim._MAX_RUNNING_EXECUTIONS - 1


# -- 1c: the scan never lists a symlink, whatever rmtree would do with it --


def test_the_scan_never_lists_a_symlink_to_a_directory(base: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "work.txt").write_text("not under the base\n")
    (base / "ws-link").symlink_to(elsewhere, target_is_directory=True)
    (base / "ws-real").mkdir()
    listed = [x.workspace_id for x in stale_dirs.scan_workspace_dirs(str(base))]
    assert listed == ["ws-real"]


# -- 2: a claim a dead pass left is returned when the directory is kept --


def _claimed_by_a_dead_pass(ws: Path) -> Path:
    claimed = ws.with_name(CLAIM_PREFIX + ws.name)
    ws.rename(claimed)
    return claimed


async def test_a_left_claim_the_guard_keeps_is_put_back(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-left-guarded", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "checkout", "-b", "agent-work")
    (app / "feature.py").write_text("x = 1\n")
    _git(app, "add", "feature.py")
    _git(app, "commit", "-m", "never pushed")
    _claimed_by_a_dead_pass(ws)
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-left-guarded",)
    assert sorted(p.name for p in base.iterdir()) == ["ws-left-guarded"]


async def test_a_left_claim_git_cannot_read_is_put_back(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-left-unreadable", tmp_path)
    _git(ws / "repos" / "app", "config", "core.sshCommand", "true")
    _claimed_by_a_dead_pass(ws)
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-left-unreadable",)
    assert sorted(p.name for p in base.iterdir()) == ["ws-left-unreadable"]


async def test_a_left_claim_kept_at_the_last_look_is_put_back(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-left-late", tmp_path)
    _claimed_by_a_dead_pass(ws)
    containers: list[WorkspaceContainer] = []
    reclaimer = _reclaimer(base, containers=containers)
    claim = reclaimer.claim

    def claim_then_mount(host_dir: str) -> str:
        claimed = claim(host_dir)
        containers.append(WorkspaceContainer("ws-left-late", "exec-late", running=True))
        return claimed

    reclaimer.claim = claim_then_mount
    result = await reclaimer.run_once()
    assert result.kept == ("ws-left-late",)
    assert sorted(p.name for p in base.iterdir()) == ["ws-left-late"]


async def test_a_left_claim_whose_path_was_retaken_stays_claimed(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-retaken", tmp_path)
    _git(ws / "repos" / "app", "config", "core.sshCommand", "true")
    claimed = _claimed_by_a_dead_pass(ws)
    ws.mkdir()
    (ws / "new.txt").write_text("a new owner's work\n")
    await _reclaimer(base).run_once()
    assert (ws / "new.txt").read_text() == "a new owner's work\n"
    assert claimed.is_dir()


# -- 3: the clock reads the coordinator the API holds now, not the first one --


async def test_reclaim_follows_the_coordinator_a_recovery_re_init_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = AsyncMock(), AsyncMock()
    first.is_live, second.is_live = True, False
    coordinators = iter([first, second])
    started: list[object] = []

    def start_once(is_live: object) -> None:
        if not started:  # as the real one: a running clock is not restarted
            started.append(is_live)

    pager_calls: list[None] = []

    def pager_fails_first_time() -> None:
        pager_calls.append(None)
        if len(pager_calls) == 1:
            raise RuntimeError("settings unreadable")

    monkeypatch.setattr(lifecycle, "get_realtime", lambda: None)
    monkeypatch.setattr(lifecycle, "get_subscription_coordinator", lambda **_kw: next(coordinators))
    monkeypatch.setattr(lifecycle, "announce_admission_if_open", AsyncMock())
    monkeypatch.setattr(lifecycle, "start_disk_recovery_watch", lambda: None)
    monkeypatch.setattr(lifecycle, "start_workspace_reclaim", start_once)
    monkeypatch.setattr(lifecycle, "start_disk_pager", pager_fails_first_time)
    monkeypatch.setattr("syn_api._wiring_inventory.get_inventory_runtime", AsyncMock)
    state = lifecycle.LifecycleState(workflow_dispatcher=AsyncMock())
    with pytest.raises(RuntimeError):
        await lifecycle._init_subscriptions(state)
    await lifecycle._init_subscriptions(state)  # the recovery loop's retry

    assert state.subscription_service is second
    (is_live,) = started
    assert callable(is_live)
    assert is_live() is False  # the first coordinator is live; the current one is not
    second.is_live = True
    assert is_live() is True
    state.subscription_service = None
    assert is_live() is False


# -- 4: a rebuilding read model skips the pass, and fails closed --


class _Service:
    def __init__(self, lag: ReadModelLag | None = None, *, fail: bool = False) -> None:
        self._lag = lag
        self._fail = fail

    async def describe_read_model_lag(self) -> ReadModelLag | None:
        if self._fail:
            raise ConnectionError("checkpoint table unreadable")
        return self._lag


def _lag(projection: str, *, position: int, head: int = 40) -> ReadModelLag:
    entry = ProjectionLag(projection=projection, position=position, lag=head - position)
    return ReadModelLag(
        is_catching_up=False, lag=entry.lag, head_position=head, lagging_projections=[entry]
    )


@pytest.mark.parametrize(
    ("service", "rebuilding"),
    [
        # rebuild_projection deleted the checkpoint: 40 events is under the
        # dashboard's 500, and still an emptied list.
        (_Service(_lag("workflow_executions", position=0)), True),
        (_Service(_lag("workspace_ownership", position=0)), True),
        (_Service(_lag("workflow_executions", position=10, head=1000)), True),
        (_Service(_lag("workflow_executions", position=35)), False),
        (_Service(_lag("evals", position=0)), False),
        (_Service(ReadModelLag(is_catching_up=False, lag=0, head_position=40)), False),
        (_Service(None), True),
        (_Service(fail=True), True),
        (None, True),
    ],
)
async def test_reclaim_inputs_rebuilding_fails_closed(
    monkeypatch: pytest.MonkeyPatch, service: _Service | None, rebuilding: bool
) -> None:
    monkeypatch.setattr(lifecycle._state, "subscription_service", service)
    reclaimer = workspace_dir_reclaim.default_reclaimer(lambda: True)
    assert (await reclaimer.read_models_rebuilding() is not None) is rebuilding


async def test_read_models_rebuilding_names_only_what_it_was_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle._state, "subscription_service", _Service(_lag("evals", position=0))
    )
    assert await read_models_rebuilding({"workflow_executions"}) is None
    assert await read_models_rebuilding({"evals"}) is not None


async def test_a_rebuild_skips_the_pass(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-rebuild", tmp_path)
    reclaimer = _reclaimer(base)

    async def rebuilding() -> str | None:
        return "workflow_executions is rebuilding (40 events behind)"

    reclaimer.read_models_rebuilding = rebuilding
    result = await reclaimer.run_once()
    assert result.skipped == "workflow_executions is rebuilding (40 events behind)"
    assert ws.exists()


async def test_a_rebuild_beginning_during_archival_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-rebuild-late", tmp_path)
    reclaimer = _reclaimer(base)
    rebuilding: list[str | None] = [None]

    async def read_models() -> str | None:
        return rebuilding[0]

    claim = reclaimer.claim

    def claim_then_rebuild(host_dir: str) -> str:
        claimed = claim(host_dir)
        rebuilding[0] = "workflow_executions is rebuilding (40 events behind)"
        return claimed

    reclaimer.read_models_rebuilding = read_models
    reclaimer.claim = claim_then_rebuild
    result = await reclaimer.run_once()
    assert result.kept == ("ws-rebuild-late",)
    assert sorted(p.name for p in base.iterdir()) == ["ws-rebuild-late"]
