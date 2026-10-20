"""Reclaim the workspace backlog as root, under enforced quiescence (#1983, design 1.5).

The automatic reclaimer runs as uid ``syn`` and cannot delete what a
workspace wrote as root; that is the 103G on the VPS. This runs once, by an
operator, as root inside the API container (``just vps-reclaim`` gets it
there), with the SAME predicate: it is a `WorkspaceDirReclaimer` built from
standalone ports, so every clause, the claim, the second look, the identity
check, the ``.deleting-`` commit point and the base-directory guard are the
ones the automatic pass uses and its tests pin.

What it adds is quiescence, checked by the tool and never taken on trust:

1. maintenance is on (``--apply`` sets it through ``PUT /maintenance`` and
   reads it back);
2. zero RUNNING executions in the read model, and zero running or paused
   ``agentic-ws-`` containers;
3. the automatic reclaimer reports ``paused: maintenance`` in /health, from a
   pass that ended after maintenance began, so it is not mid-delete.

All three are read again before EVERY directory (the reclaimer's ``paused``
hook), and any change stops the run there: directories already deleted stay
deleted, the rest are untouched. A ``--budget-minutes`` bound (default 10)
keeps one run from holding maintenance for the whole backlog; a directory cut
off mid-delete keeps its ``.deleting-`` name and the next run finishes it.

Dry run is the default: every clause is evaluated read-only and nothing is
renamed or deleted. Maintenance is lifted only with ``--lift-maintenance``.

SCRATCH ONLY. Like the automatic pass it deletes nothing but direct children
of the workspace base; run history is kept for every run.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - read by the dataclass annotations
from typing import TYPE_CHECKING, cast

from pydantic import JsonValue

from syn_shared.env_constants import ENV_SYN_API_PORT
from syn_shared.settings.constants import API_CONTAINER_PORT

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from syn_adapters.session_inventory.database import Pool as InventoryPool
    from syn_api.services.workspace_dir_reclaim import ReclaimPass, WorkspaceDirReclaimer

#: /health reasons that mean a read model this tool trusts may be incomplete.
_READ_MODEL_REASONS = frozenset(
    {
        "subscription_coordinator",
        "projection_catchup",
        "projection_stalled",
        "projection_dropped_event",
        "projection_held",
        "subscription_halted",
    }
)

_MAX_RUNNING = 500


@dataclass(frozen=True)
class SubscriptionProof:
    """The read path as /health's ``subscription`` block states it.

    Every field is what the API said, or None when it did not say. Only an
    affirmative answer on all of them proves the read models complete.
    """

    status: str | None = None
    running: bool | None = None
    is_catching_up: bool | None = None
    lag: int | None = None
    halted_at: int | None = None
    held: int | None = None
    lagging: int | None = None
    rebuilding: int | None = None


def subscription_unproven(proof: SubscriptionProof | None) -> str | None:
    """None only for a healthy, running, caught-up read path at lag 0. Fail closed."""
    if proof is None:
        return "/health has no subscription block; read-model completeness is unproven"
    checks = (
        (proof.status == "healthy", f"subscription status is {proof.status}"),
        (proof.running is True, f"subscription running is {proof.running}"),
        (proof.is_catching_up is False, f"is_catching_up is {proof.is_catching_up}"),
        (proof.lag == 0, f"subscription lag is {proof.lag}"),
        (proof.halted_at is None, f"subscription halted at {proof.halted_at}"),
        (not proof.held, f"{proof.held} projection(s) held"),
        (not proof.lagging, f"{proof.lagging} projection(s) lagging"),
        (not proof.rebuilding, f"{proof.rebuilding} read model(s) rebuilding"),
    )
    failed = [why for ok, why in checks if not ok]
    if failed:
        return "read-model completeness is unproven: " + "; ".join(failed)
    return None


@dataclass(frozen=True)
class QuiescenceState:
    """Everything the run must see before each delete."""

    maintenance: bool
    maintenance_since: datetime | None
    running_executions: int
    live_workspace_containers: tuple[str, ...]
    reclaimer_paused: str | None
    reclaimer_last_pass_at: datetime | None
    degraded_reasons: tuple[str, ...] = ()
    #: None when /health carried no subscription block.
    subscription: SubscriptionProof | None = None


def parse_quiescence(
    maintenance_json: bytes,
    health_json: bytes,
    *,
    running_executions: int,
    live_containers: tuple[str, ...],
) -> QuiescenceState:
    """Read the API's answers through its own published models: frozen, extra forbidden.

    A field the API does not publish, or one it no longer does, is contract
    drift, and drift raises here instead of reading as "quiet".

    /health is read block by block: its serialized form carries computed
    display fields (``build.started_at_display``) that its own input model
    forbids, so the whole document cannot round-trip. Its top-level keys must
    all be declared fields, and the two blocks this tool decides on - ``disk``
    and ``degraded_reasons`` - are validated through their published models.
    """
    from pydantic import TypeAdapter

    from syn_api.services.degraded_reasons import DegradedReason
    from syn_api.types import (
        DiskSpaceHealth,
        HealthResponse,
        MaintenanceModeResponse,
    )

    maintenance = MaintenanceModeResponse.model_validate_json(maintenance_json)
    document = TypeAdapter(dict[str, JsonValue]).validate_json(health_json)
    unknown = sorted(set(document) - set(HealthResponse.model_fields))
    if unknown:
        raise ValueError(f"/health publishes fields this tool does not know: {unknown}")
    disk_block = document.get("disk")
    disk = None if disk_block is None else DiskSpaceHealth.model_validate(disk_block)
    reasons = TypeAdapter(list[DegradedReason] | None).validate_python(
        document.get("degraded_reasons")
    )
    reclaim = None if disk is None else disk.reclaim
    subscription = _subscription_proof(document.get("subscription"))
    return QuiescenceState(
        maintenance=maintenance.active,
        maintenance_since=maintenance.since,
        running_executions=running_executions,
        live_workspace_containers=live_containers,
        reclaimer_paused=None if reclaim is None else reclaim.paused,
        reclaimer_last_pass_at=None if reclaim is None else reclaim.last_pass_at,
        degraded_reasons=tuple(str(r) for r in reasons or ()),
        subscription=subscription,
    )


def _count(items: Sequence[object] | None) -> int | None:
    return None if items is None else len(items)


def _subscription_proof(block: JsonValue) -> SubscriptionProof | None:
    """The /health subscription block through ``SubscriptionHealth``; None when absent."""
    from syn_api.types import SubscriptionHealth

    if block is None:
        return None
    read = SubscriptionHealth.model_validate(block)
    return SubscriptionProof(
        status=read.status,
        running=read.running,
        is_catching_up=read.is_catching_up,
        lag=read.lag,
        halted_at=read.halted_at,
        held=_count(read.held_projections),
        lagging=_count(read.lagging_projections),
        rebuilding=_count(read.rebuilding_read_models),
    )


@dataclass
class QuiescenceGate:
    """The one answer to "may the next destructive step run", read fresh each time.

    The reclaimer asks it (``paused``) right before the claim, the mark and
    the delete, and its ``is_live`` reads the answer that check just got, so
    a lost quiescence stops the next step whichever hook asks first. An
    unreadable answer is not quiet.
    """

    quiescence: ApiQuiescence
    apply: bool
    #: The last answer: True only while the last read found the host quiescent.
    quiet: bool = False

    def __post_init__(self) -> None:
        self.quiet = not self.apply

    async def stop_reason(self) -> str | None:
        if not self.apply:
            return None
        try:
            reason = quiescence_lost(await self.quiescence.read())
        except Exception as exc:
            reason = f"quiescence unreadable ({type(exc).__name__}: {exc})"
        self.quiet = reason is None
        return reason

    def is_live(self) -> bool:
        return self.quiet

    async def completeness(self) -> str | None:
        """The reclaimer's read-model completeness hook: None only when proven, read fresh.

        Asked in dry runs too: a verdict over incomplete read models is wrong
        either way, so an unproven read path skips the pass.
        """
        try:
            state = await self.quiescence.read()
        except Exception as exc:
            return f"completeness unreadable ({type(exc).__name__}: {exc})"
        return subscription_unproven(state.subscription)


def quiescence_lost(state: QuiescenceState) -> str | None:
    """Why it is NOT safe to delete now, or None. Pure, so every case is a test."""
    if not state.maintenance:
        return "maintenance is not on"
    if state.running_executions:
        return f"{state.running_executions} execution(s) are RUNNING"
    if state.live_workspace_containers:
        return f"workspace container(s) running or paused: {list(state.live_workspace_containers)}"
    if state.reclaimer_paused != "maintenance":
        return f"the automatic reclaimer is not paused for maintenance ({state.reclaimer_paused})"
    since, last = state.maintenance_since, state.reclaimer_last_pass_at
    if since is None or last is None or last < since:
        return (
            "the automatic reclaimer has not finished a pass since maintenance began; "
            "rerun after its next pass (SYN_DISK_RECLAIM_INTERVAL_MINUTES)"
        )
    rebuilding = sorted(_READ_MODEL_REASONS & set(state.degraded_reasons))
    if rebuilding:
        return f"read models may be incomplete: {rebuilding}"
    return subscription_unproven(state.subscription)


@dataclass(frozen=True)
class RunOptions:
    apply: bool
    budget_seconds: float
    lift_maintenance: bool


async def run(
    options: RunOptions,
    quiescence: ApiQuiescence,
    build_reclaimer: Callable[[QuiescenceGate, RunOptions], WorkspaceDirReclaimer],
    out: Callable[[str], None] = print,
) -> int:
    """The tool. Exit code 0 when it ran (or dry-ran) to completion, 2 when it refused."""
    gate = QuiescenceGate(quiescence, apply=options.apply)
    if options.apply:
        try:
            if not (await quiescence.read()).maintenance:
                await quiescence.set_maintenance(True, "vps-reclaim: workspace backlog (#1983)")
        except Exception as exc:
            out(f"REFUSED: could not set maintenance ({type(exc).__name__}: {exc})")
            return 2
        refused = await gate.stop_reason()
        if refused is not None:
            out(f"REFUSED: {refused}")
            return 2

    reclaimer = build_reclaimer(gate, options)
    result = await reclaimer.run_once()
    _report(result, out, apply=options.apply)
    if options.lift_maintenance and options.apply:
        await quiescence.set_maintenance(False, "")
        out("maintenance lifted")
    if result.paused is not None or result.skipped is not None:
        out(f"STOPPED: {result.paused or result.skipped}")
        return 2
    return 0


def _report(result: ReclaimPass, out: Callable[[str], None], *, apply: bool) -> None:
    for kept in result.retained:
        out(f"retained {kept.workspace_id} {kept.size_bytes} {kept.reason.value}: {kept.detail}")
    for workspace_id in result.would_reclaim:
        out(f"would reclaim {workspace_id}")
    for workspace_id in result.reclaimed:
        out(f"reclaimed {workspace_id}")
    for workspace_id in result.deleting:
        out(f"deleting {workspace_id} (out of time; rerun to finish)")
    mode = "apply" if apply else "dry run"
    out(
        f"{mode}: reclaimed {len(result.reclaimed)} ({result.reclaimed_bytes} bytes), "
        f"would reclaim {len(result.would_reclaim)}, retained {len(result.retained)}, "
        f"deleting {len(result.deleting)}, out of time {result.out_of_time}"
    )


# -- production ports ----------------------------------------------------------


class ApiQuiescence:
    """Reads maintenance and /health from the API in this container, the rest directly."""

    def __init__(self, api: str, running: Callable[[], Awaitable[int]]) -> None:
        self._api = api
        self._running = running

    async def read(self) -> QuiescenceState:
        return parse_quiescence(
            await _http(f"{self._api}/maintenance"),
            await _http(f"{self._api}/health"),
            running_executions=await self._running(),
            live_containers=await live_workspace_containers(),
        )

    async def set_maintenance(self, active: bool, reason: str) -> None:
        from syn_api.types import SetMaintenanceModeRequest

        body = SetMaintenanceModeRequest(active=active, reason=reason, actor="vps-reclaim")
        await _http(f"{self._api}/maintenance", method="PUT", body=body.model_dump_json().encode())


async def _http(url: str, *, method: str = "GET", body: bytes | None = None) -> bytes:
    def call() -> bytes:
        request = urllib.request.Request(
            url, data=body, method=method, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"{method} {url} answered {response.status}")
            return response.read()

    return await asyncio.to_thread(call)


async def live_workspace_containers() -> tuple[str, ...]:
    """Running or paused ``agentic-ws-`` containers. Raises when docker cannot answer."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "-q",
        "--filter",
        "name=agentic-ws-",
        "--filter",
        "status=running",
        "--filter",
        "status=paused",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"docker ps exited {proc.returncode}")
    return tuple(stdout.decode().split())


def _source_instance_id(archive_dir: Path) -> str:
    """Read the installation id the API wrote; never create one as root."""
    return (archive_dir / ".source-instance-id").read_text().strip()


def production_reclaimer(gate: QuiescenceGate, options: RunOptions) -> WorkspaceDirReclaimer:
    """The automatic reclaimer's predicate over standalone read models, as root."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.session_inventory.postgres_spools import PostgresCaptureSpools
    from syn_adapters.workspace_backends.orphaned import workspace_base_dir, workspace_host_dir
    from syn_adapters.workspace_backends.remote_refs import GitLsRemote, github_app_credential
    from syn_adapters.workspace_backends.stale_dirs import (
        SubprocessHostWorkspaceGit,
        list_containers,
        own_container_id,
        scan_workspace_dirs,
    )
    from syn_api._wiring_db import get_shared_db_pool
    from syn_api.services.workspace_dir_reclaim import (
        ReclaimReadModels,
        WorkspaceDirReclaimer,
    )
    from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
        SessionListProjection,
    )
    from syn_domain.contexts.orchestration.slices.list_executions.projection import (
        WorkflowExecutionListProjection,
    )
    from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
        WorkspaceOwnershipProjection,
    )
    from syn_shared.settings import get_settings

    settings = get_settings()
    store = get_projection_store()
    pool = get_shared_db_pool()
    if pool is None:
        raise RuntimeError("vps-reclaim needs the database (SYN_OBSERVABILITY_DB_URL)")
    # asyncpg's stubs omit the connection interface; see _wiring_inventory.
    spools = PostgresCaptureSpools(
        cast("InventoryPool", pool), _source_instance_id(settings.session_inventory.archive_dir)
    )
    models = ReclaimReadModels(
        WorkflowExecutionListProjection(store), spools, SessionListProjection(store)
    )

    return WorkspaceDirReclaimer(
        base_dir=workspace_base_dir(),
        settle_seconds=settings.disk.reclaim_settle_minutes * 60,
        list_containers=list_containers,
        workspace_owners=WorkspaceOwnershipProjection(store).owners,
        execution_record=models.execution_record,
        capture_unproven=models.capture_unproven,
        scan_dirs=scan_workspace_dirs,
        git=SubprocessHostWorkspaceGit(),
        remotes=GitLsRemote(github_app_credential),
        paused=gate.stop_reason,
        is_live=gate.is_live,
        host_base_dir=workspace_host_dir(),
        own_container=own_container_id(),
        observer_containers=settings.disk.observer_container_names(),
        # Completeness is proven from the subscription block, or the pass is skipped.
        read_models_rebuilding=gate.completeness,
        pass_budget_seconds=options.budget_seconds,
        dry_run=not options.apply,
    )


async def _running_executions() -> int:
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.orchestration.slices.list_executions.projection import (
        WorkflowExecutionListProjection,
    )

    rows = await WorkflowExecutionListProjection(get_projection_store()).get_all(
        limit=_MAX_RUNNING, status_filter="running"
    )
    # A full page may be truncated: report it as "at least", never as fewer.
    return len(rows)


def parse_args(argv: Sequence[str]) -> RunOptions:
    parser = argparse.ArgumentParser(
        prog="vps-reclaim",
        description="Reclaim the workspace backlog as root, under enforced quiescence.",
    )
    parser.add_argument("--apply", action="store_true", help="rename and delete (default: dry run)")
    parser.add_argument(
        "--budget-minutes",
        type=float,
        default=10.0,
        help="stop starting deletes after this long; rerun to continue (default 10)",
    )
    parser.add_argument(
        "--lift-maintenance", action="store_true", help="clear maintenance after an --apply run"
    )
    args = parser.parse_args(list(argv))
    if args.budget_minutes <= 0:
        parser.error("--budget-minutes must be positive")
    return RunOptions(
        apply=args.apply,
        budget_seconds=args.budget_minutes * 60,
        lift_maintenance=args.lift_maintenance,
    )


async def _main(argv: Sequence[str]) -> int:
    from syn_api._wiring_db import close_shared_db_pool, init_shared_db_pool

    options = parse_args(argv)
    await init_shared_db_pool()
    port = os.environ.get(ENV_SYN_API_PORT, str(API_CONTAINER_PORT))
    try:
        return await run(
            options,
            ApiQuiescence(f"http://127.0.0.1:{port}", _running_executions),
            production_reclaimer,
        )
    finally:
        await close_shared_db_pool()


def main() -> None:
    started = time.monotonic()
    code = asyncio.run(_main(sys.argv[1:]))
    print(f"vps-reclaim finished in {time.monotonic() - started:.0f}s")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
