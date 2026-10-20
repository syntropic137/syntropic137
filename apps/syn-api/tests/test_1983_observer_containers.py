"""#1983, first live pass: node-exporter's ``/`` bind held every workspace.

A container binding an ancestor of the workspace base reaches every
workspace, and it keeps blocking reclaim whether its bind is read-only or not:
read-only does not mean unused, and ``RW: false`` alone does not keep
submounts read-only. The one exemption is EXPLICIT: a container the operator
lists in ``SYN_DISK_RECLAIM_OBSERVER_CONTAINERS`` is skipped only while its own
inspect shows every observer condition, re-read on every pass.

Every case runs through the real ``docker inspect`` parser and
``list_containers`` with docker's document shape (verified against Engine
29.8.0), then a real reclaim pass over a real git workspace. Only the docker
subprocess is a double.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from test_pc130_workspace_dir_reclaim import HOST_BASE, _reason, _reclaimer, _workspace

from syn_adapters.workspace_backends import stale_dirs
from syn_adapters.workspace_backends.orphaned import parse_inspect
from syn_domain.contexts.orchestration import RetainedReason
from syn_shared.settings.disk import DiskSettings

if TYPE_CHECKING:
    from pathlib import Path

    from syn_api.services.workspace_dir_reclaim import ReclaimPass

pytestmark = pytest.mark.unit

_NODE_EXPORTER = "flywheel-observability-node-exporter"
_ID = "5c0ffee1234567890abcdef0"


@dataclass(frozen=True)
class _Mount:
    """One ``Mounts`` record as docker writes it. ``rw`` is written verbatim, or omitted."""

    source: str = "/"
    destination: str = "/host"
    rw: object = False
    propagation: str | None = "rprivate"
    type: str = "bind"

    def record(self) -> object:
        entry = {"Type": self.type, "Source": self.source, "Destination": self.destination}
        if self.rw is not _OMIT:
            entry["RW"] = self.rw  # type: ignore[assignment]
            entry["Mode"] = "ro" if self.rw is False else "rw"
        if self.propagation is not None:
            entry["Propagation"] = self.propagation
        return entry


_OMIT = object()


#: ``BindOptions`` for ``bind-recursive=readonly,bind-propagation=rprivate``.
_FORCED = ("/host", '{"Propagation": "rprivate", "ReadOnlyForceRecursive": true}')


@dataclass(frozen=True)
class _Container:
    """One ``docker inspect`` document; defaults are the VPS node-exporter shape."""

    name: str = _NODE_EXPORTER
    mounts: tuple[_Mount, ...] = (_Mount(),)
    privileged: object = False
    cap_add: tuple[str, ...] | None = None
    #: ``HostConfig.Mounts``, for ``--mount`` binds: (target, BindOptions JSON).
    #: The default is what Engine 29.8.0 reports for the required observer line
    #: ``--mount type=bind,source=/,target=/host,readonly,bind-recursive=readonly,
    #: bind-propagation=rprivate``.
    host_mounts: tuple[tuple[str, str], ...] = (_FORCED,)
    host_config: bool = True
    extra: tuple[tuple[str, object], ...] = field(default=())

    def inspect(self) -> str:
        host = {"CapAdd": list(self.cap_add) if self.cap_add is not None else None}
        if self.privileged is not _OMIT:
            host["Privileged"] = self.privileged  # type: ignore[assignment]
        if self.host_mounts:
            host["Mounts"] = [  # type: ignore[assignment]
                {"Type": "bind", "Target": target, "BindOptions": json.loads(options)}
                for target, options in self.host_mounts
            ]
        document = {
            "Id": _ID,
            "Name": f"/{self.name}",
            "State": {"Running": True, "Paused": False},
            "Config": {"Labels": {}},
            "Mounts": [m.record() for m in self.mounts],
        }
        if self.host_config:
            document["HostConfig"] = host  # type: ignore[assignment]
        return json.dumps([document])


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


def _docker_with(monkeypatch: pytest.MonkeyPatch, container: _Container) -> None:
    """``docker ps`` lists one container; ``docker inspect`` answers with it. Git is real."""

    class _Ps:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return f"{_ID}\n".encode(), None

    real_exec = stale_dirs.asyncio.create_subprocess_exec

    async def ps(*argv: str, **kwargs: object) -> object:
        if argv and argv[0] == "docker":
            return _Ps()
        return await real_exec(*argv, **kwargs)  # type: ignore[arg-type]

    async def inspect(container_id: str) -> str:
        return container.inspect()

    monkeypatch.setattr(stale_dirs.asyncio, "create_subprocess_exec", ps)
    monkeypatch.setattr(stale_dirs, "docker_inspect_raw", inspect)


async def _pass(
    base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: _Container,
    *,
    listed: frozenset[str],
) -> ReclaimPass:
    _workspace(base, "ws-observed", tmp_path)
    _docker_with(monkeypatch, container)
    reclaimer = _reclaimer(base)
    reclaimer.list_containers = stale_dirs.list_containers
    reclaimer.observer_containers = listed
    return await reclaimer.run_once()


_LISTED = frozenset({_NODE_EXPORTER})


# --- the exemption ---


@pytest.mark.parametrize(
    "propagation",
    ["rprivate", None],
    ids=["rprivate", "absent-means-documented-default"],
)
async def test_a_listed_observer_meeting_every_condition_is_exempt(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, propagation: str | None
) -> None:
    """The required observer line: ``/`` at /host, read-only, forced recursive, rprivate."""
    container = _Container(mounts=(_Mount(propagation=propagation),))
    result = await _pass(base, tmp_path, monkeypatch, container, listed=_LISTED)
    assert result.reclaimed == ("ws-observed",)
    assert not (base / "ws-observed").exists()


async def test_the_same_shape_unlisted_blocks_and_names_the_container(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = await _pass(base, tmp_path, monkeypatch, _Container(), listed=frozenset())
    assert _reason(result, "ws-observed") is RetainedReason.MOUNTED
    [kept] = result.retained
    assert f"{_NODE_EXPORTER} ({_ID[:12]})" in kept.detail
    assert (base / "ws-observed").exists()


async def test_an_active_read_only_reader_of_the_base_that_is_not_listed_blocks(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex r1: read-only does not mean unused; a terminal owner proves nothing about it."""
    reader = _Container(
        name="report-builder", mounts=(_Mount(source=HOST_BASE, destination="/in"),)
    )
    result = await _pass(base, tmp_path, monkeypatch, reader, listed=_LISTED)
    assert _reason(result, "ws-observed") is RetainedReason.MOUNTED
    assert "report-builder" in result.retained[0].detail


# --- each condition, failing alone, keeps the directory and says why ---


@pytest.mark.parametrize(
    ("container", "why"),
    [
        (_Container(privileged=True), "privileged"),
        (_Container(privileged=_OMIT), "privileged"),
        (_Container(cap_add=("SYS_ADMIN",)), "SYS_ADMIN"),
        (_Container(cap_add=("ALL",)), "SYS_ADMIN"),
        (_Container(host_config=False), "HostConfig is unknown"),
        (_Container(mounts=(_Mount(propagation="rslave"),)), "rslave propagation"),
        (_Container(mounts=(_Mount(propagation="rshared"),)), "rshared propagation"),
        (_Container(mounts=(_Mount(propagation="private"),)), "private propagation"),
        (_Container(mounts=(_Mount(rw=_OMIT),)), "not read-only (RW None)"),
        (
            _Container(mounts=(_Mount(), _Mount(destination="/rw", rw=True))),
            "/rw is not read-only",
        ),
        (
            _Container(mounts=(_Mount(destination="/rw", rw=True), _Mount())),
            "/rw is not read-only",
        ),
        (
            _Container(
                mounts=(_Mount(), _Mount(type="volume", source="/var/lib/docker/v", rw=True))
            ),
            "is not read-only",
        ),
        (_Container(host_mounts=()), "not forced recursively read-only"),
        (
            _Container(host_mounts=(("/host", '{"ReadOnlyForceRecursive": false}'),)),
            "not forced recursively read-only",
        ),
        (
            _Container(host_mounts=(("/host", '{"Propagation": "rprivate"}'),)),
            "not forced recursively read-only",
        ),
        (
            _Container(host_mounts=(("/host", '{"ReadOnlyNonRecursive": true}'),)),
            "not forced recursively read-only",
        ),
        (
            _Container(host_mounts=(("/elsewhere", _FORCED[1]),)),
            "not forced recursively read-only",
        ),
    ],
    ids=[
        "privileged",
        "privileged-unknown",
        "cap-sys-admin",
        "cap-all",
        "no-hostconfig",
        "rslave",
        "rshared",
        "private-is-not-recursive",
        "rw-missing",
        "rw-duplicate-after",
        "rw-duplicate-before",
        "writable-volume",
        "dash-v-form-cannot-say-recursive",
        "force-recursive-false",
        "force-recursive-missing",
        "bind-recursive-writable",
        "force-recursive-on-another-target",
    ],
)
async def test_a_listed_observer_failing_any_condition_blocks_and_says_which(
    base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: _Container,
    why: str,
) -> None:
    result = await _pass(base, tmp_path, monkeypatch, container, listed=_LISTED)
    assert _reason(result, "ws-observed") is RetainedReason.MOUNTED
    [kept] = result.retained
    assert _NODE_EXPORTER in kept.detail
    assert "a listed observer, but" in kept.detail
    assert why in kept.detail
    assert (base / "ws-observed").exists()


@pytest.mark.parametrize("rw", ["false", 0, "off", "no"])
async def test_a_coercible_rw_value_is_not_read_only_and_skips_the_pass(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rw: object
) -> None:
    """Codex r1 P2: StrictBool. ``"false"`` is not ``false``; the document is unreadable."""
    container = _Container(mounts=(_Mount(rw=rw),))
    assert parse_inspect(container.inspect()) is None
    result = await _pass(base, tmp_path, monkeypatch, container, listed=_LISTED)
    assert result.skipped is not None
    assert (base / "ws-observed").exists()


def test_the_vps_shape_parses_as_a_pure_observer() -> None:
    inspected = parse_inspect(_Container().inspect())
    assert inspected is not None
    assert inspected.name == _NODE_EXPORTER
    assert inspected.observer_unsafe is None


def test_the_exemption_is_by_exact_name() -> None:
    settings = DiskSettings(
        _env_file=None,  # type: ignore[call-arg]
        reclaim_observer_containers=" flywheel-observability-node-exporter , ,other ",
    )
    assert settings.observer_container_names() == frozenset(
        {"flywheel-observability-node-exporter", "other"}
    )
    assert DiskSettings(_env_file=None).observer_container_names() == frozenset()  # type: ignore[call-arg]


def test_the_production_reclaimer_reads_the_observer_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.services.workspace_dir_reclaim import default_reclaimer

    # Read fresh from the environment, as the deployed API reads it.
    monkeypatch.setenv("SYN_DISK_RECLAIM_OBSERVER_CONTAINERS", _NODE_EXPORTER)
    assert default_reclaimer(lambda: True).observer_containers == _LISTED


@pytest.mark.parametrize("value", ['"true"', "1"])
async def test_a_coercible_force_recursive_value_skips_the_pass(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """StrictBool again: ``"true"`` or ``1`` is not the proof; the document is unreadable."""
    container = _Container(host_mounts=(("/host", f'{{"ReadOnlyForceRecursive": {value}}}'),))
    assert parse_inspect(container.inspect()) is None
    result = await _pass(base, tmp_path, monkeypatch, container, listed=_LISTED)
    assert result.skipped is not None
    assert (base / "ws-observed").exists()
