"""#1983 design 1.5: ``vps-reclaim`` deletes only under quiescence it checks itself.

`run` is driven with a fake quiescence port and the REAL reclaimer over real
git workspaces (the helpers of test_pc130_workspace_dir_reclaim), so a refusal
is proven by what is still on disk, not by a return value alone.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from test_pc130_workspace_dir_reclaim import _reclaimer, _workspace

from syn_adapters.workspace_backends.stale_dirs import (
    CLAIM_PREFIX,
    claim_workspace_dir,
    mark_for_deletion,
)
from syn_api.vps_reclaim import QuiescenceState, RunOptions, parse_args, quiescence_lost, run
from syn_domain.contexts.orchestration import RetainedReason

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_api.services.workspace_dir_reclaim import WorkspaceDirReclaimer

pytestmark = pytest.mark.unit

_SINCE = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
_QUIET = QuiescenceState(
    maintenance=True,
    maintenance_since=_SINCE,
    running_executions=0,
    live_workspace_containers=(),
    reclaimer_paused="maintenance",
    reclaimer_last_pass_at=_SINCE + timedelta(minutes=30),
)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


# --- the quiescence rule, case by case ---


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"maintenance": False}, "maintenance is not on"),
        ({"running_executions": 1}, "RUNNING"),
        ({"live_workspace_containers": ("abc123",)}, "running or paused"),
        ({"reclaimer_paused": None}, "not paused for maintenance"),
        ({"reclaimer_last_pass_at": _SINCE - timedelta(minutes=1)}, "has not finished a pass"),
        ({"reclaimer_last_pass_at": None}, "has not finished a pass"),
        ({"maintenance_since": None}, "has not finished a pass"),
        ({"degraded_reasons": ("projection_catchup",)}, "read models may be incomplete"),
    ],
)
def test_each_missing_condition_refuses(change: dict[str, object], why: str) -> None:
    refused = quiescence_lost(replace(_QUIET, **change))  # type: ignore[arg-type]
    assert refused is not None
    assert why in refused


def test_a_quiet_host_with_an_unrelated_degradation_is_quiescent() -> None:
    assert quiescence_lost(replace(_QUIET, degraded_reasons=("disk_space",))) is None


# --- the run ---


class _Port:
    """Quiescence as a sequence of states: each read returns the next, the last repeats."""

    def __init__(self, *states: QuiescenceState) -> None:
        self.states = list(states)
        self.reads = 0
        self.set_calls: list[bool] = []

    async def read(self) -> QuiescenceState:
        state = self.states[min(self.reads, len(self.states) - 1)]
        self.reads += 1
        return state

    async def set_maintenance(self, active: bool, reason: str) -> None:
        self.set_calls.append(active)


def _builder(
    base: Path, built: list[WorkspaceDirReclaimer]
) -> Callable[[Callable[[], Awaitable[str | None]], RunOptions], WorkspaceDirReclaimer]:
    def build(
        stop: Callable[[], Awaitable[str | None]], options: RunOptions
    ) -> WorkspaceDirReclaimer:
        reclaimer = _reclaimer(base)
        reclaimer.paused = stop
        reclaimer.dry_run = not options.apply
        reclaimer.pass_budget_seconds = options.budget_seconds
        built.append(reclaimer)
        return reclaimer

    return build


_APPLY = RunOptions(apply=True, budget_seconds=600.0, lift_maintenance=False)


@pytest.mark.parametrize(
    "unquiet",
    [
        replace(_QUIET, running_executions=2),
        replace(_QUIET, live_workspace_containers=("ws-running",)),
        replace(_QUIET, reclaimer_paused=None),
    ],
)
async def test_apply_refuses_before_touching_anything_when_not_quiescent(
    base: Path, tmp_path: Path, unquiet: QuiescenceState
) -> None:
    ws = _workspace(base, "ws-held", tmp_path)
    built: list[WorkspaceDirReclaimer] = []
    lines: list[str] = []
    code = await run(_APPLY, _Port(unquiet), _builder(base, built), lines.append)
    assert code == 2
    assert built == []  # never even built the reclaimer
    assert lines[0].startswith("REFUSED:")
    assert ws.exists()


async def test_apply_sets_maintenance_and_refuses_when_it_does_not_read_back(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-no-maint", tmp_path)
    port = _Port(replace(_QUIET, maintenance=False))
    built: list[WorkspaceDirReclaimer] = []
    code = await run(_APPLY, port, _builder(base, built), lambda _line: None)
    assert port.set_calls == [True]
    assert code == 2
    assert built == []
    assert ws.exists()


async def test_maintenance_lifted_mid_run_stops_before_the_next_delete(
    base: Path, tmp_path: Path
) -> None:
    first = _workspace(base, "ws-a", tmp_path)
    second = _workspace(base, "ws-b", tmp_path)
    # Reads: two up front, one as the pass starts, then one before each directory.
    port = _Port(_QUIET, _QUIET, _QUIET, _QUIET, replace(_QUIET, maintenance=False))
    lines: list[str] = []
    code = await run(_APPLY, port, _builder(base, []), lines.append)
    assert code == 2
    assert not first.exists()
    assert second.exists()
    assert any("maintenance is not on" in line for line in lines)


async def test_a_quiet_apply_deletes_and_lifts_maintenance_only_when_asked(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-go", tmp_path)
    port = _Port(_QUIET)
    options = replace(_APPLY, lift_maintenance=True)
    code = await run(options, port, _builder(base, []), lambda _line: None)
    assert code == 0
    assert not ws.exists()
    assert port.set_calls == [False]


async def test_dry_run_needs_no_quiescence_and_changes_nothing(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-dry", tmp_path)
    port = _Port(replace(_QUIET, maintenance=False, running_executions=3))
    lines: list[str] = []
    dry = RunOptions(apply=False, budget_seconds=600.0, lift_maintenance=False)
    code = await run(dry, port, _builder(base, []), lines.append)
    assert code == 0
    assert port.set_calls == []
    assert "would reclaim ws-dry" in lines
    assert sorted(p.name for p in base.iterdir()) == ["ws-dry"]
    assert ws.exists()


# --- identity revalidation between the check and the delete ---


def test_an_inode_swapped_under_the_claim_is_refused(base: Path) -> None:
    ws = base / "ws-swap"
    ws.mkdir()
    stat = ws.lstat()
    claimed = Path(claim_workspace_dir(str(ws)))
    claimed.rename(base / "elsewhere")
    claimed.mkdir()
    with pytest.raises(FileExistsError, match="not the directory that was judged"):
        mark_for_deletion(str(claimed), (stat.st_dev, stat.st_ino))
    assert claimed.is_dir()


def test_a_symlink_swapped_in_under_the_claim_is_refused(base: Path, tmp_path: Path) -> None:
    ws = base / "ws-link"
    ws.mkdir()
    stat = ws.lstat()
    claimed = Path(claim_workspace_dir(str(ws)))
    target = tmp_path / "precious"
    claimed.rename(target)
    claimed.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        mark_for_deletion(str(claimed), (stat.st_dev, stat.st_ino))
    assert target.is_dir()


async def test_the_reclaimer_puts_back_a_dir_swapped_before_the_mark(
    base: Path, tmp_path: Path
) -> None:
    _workspace(base, "ws-late-swap", tmp_path)
    reclaimer = _reclaimer(base)
    real_mark = reclaimer.mark_deleting

    def swap_then_mark(claimed: str, identity: tuple[int, int]) -> str:
        Path(claimed).rename(tmp_path / "moved")
        os.mkdir(claimed)  # noqa: PTH102
        return real_mark(claimed, identity)

    reclaimer.mark_deleting = swap_then_mark
    result = await reclaimer.run_once()
    [kept] = result.retained
    assert kept.reason is RetainedReason.IDENTITY_CHANGED
    assert (tmp_path / "moved").is_dir()
    assert not any(p.name.startswith(CLAIM_PREFIX) for p in base.iterdir())


def test_arguments_default_to_a_dry_run_with_a_budget() -> None:
    options = parse_args([])
    assert options == RunOptions(apply=False, budget_seconds=600.0, lift_maintenance=False)
    assert parse_args(["--apply", "--budget-minutes", "2"]).budget_seconds == 120.0
    with pytest.raises(SystemExit):
        parse_args(["--budget-minutes", "0"])
