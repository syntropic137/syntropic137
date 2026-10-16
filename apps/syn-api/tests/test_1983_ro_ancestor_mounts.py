"""#1983, first live pass: node-exporter's read-only ``/`` bind blocked every reclaim.

A container binding an ANCESTOR of a workspace read-only cannot have written
work into it, so it no longer blocks. Everything else that blocked still does:
a read-write ancestor, any bind of the directory itself or inside it, and a
mount whose ``RW`` docker did not report. Driven through the real
``docker inspect`` parser and ``list_containers`` with docker's own document
shape; only the docker subprocess is a double.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from test_pc130_workspace_dir_reclaim import HOST_BASE, _reason, _reclaimer, _workspace

from syn_adapters.workspace_backends import stale_dirs
from syn_adapters.workspace_backends.orphaned import parse_inspect
from syn_adapters.workspace_backends.stale_dirs import ContainerMounts
from syn_domain.contexts.orchestration import RetainedReason

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_NODE_EXPORTER = "flywheel-observability-node-exporter"
_NODE_EXPORTER_ID = "5c0ffee1234567890abcdef"


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


def _inspect_doc(mount: dict[str, object]) -> str:
    """One ``docker inspect`` document, as docker writes it for node-exporter."""
    return json.dumps(
        [
            {
                "Id": _NODE_EXPORTER_ID,
                "Name": f"/{_NODE_EXPORTER}",
                "State": {"Running": True, "Paused": False},
                "Config": {"Labels": {}},
                "Mounts": [mount],
            }
        ]
    )


def _docker_with(monkeypatch: pytest.MonkeyPatch, document: str) -> None:
    class _Ps:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return f"{_NODE_EXPORTER_ID}\n".encode(), None

    real_exec = stale_dirs.asyncio.create_subprocess_exec

    async def ps(*argv: str, **kwargs: object) -> object:
        # Only `docker ps` is a double; host git still runs for real.
        if argv and argv[0] == "docker":
            return _Ps()
        return await real_exec(*argv, **kwargs)  # type: ignore[arg-type]

    async def inspect(container_id: str) -> str:
        return document

    monkeypatch.setattr(stale_dirs.asyncio, "create_subprocess_exec", ps)
    monkeypatch.setattr(stale_dirs, "docker_inspect_raw", inspect)


_ROOT_RO = {
    "Type": "bind",
    "Source": "/",
    "Destination": "/host",
    "Mode": "ro",
    "RW": False,
    "Propagation": "rslave",
}


async def test_a_read_only_bind_of_the_root_no_longer_blocks(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live VPS case: node-exporter's ``/:/host:ro`` held every workspace."""
    ws = _workspace(base, "ws-under-node-exporter", tmp_path)
    _docker_with(monkeypatch, _inspect_doc(_ROOT_RO))
    reclaimer = _reclaimer(base)
    reclaimer.list_containers = stale_dirs.list_containers
    result = await reclaimer.run_once()
    assert result.reclaimed == ("ws-under-node-exporter",)
    assert not ws.exists()


@pytest.mark.parametrize(
    "mount",
    [
        {**_ROOT_RO, "Mode": "rw", "RW": True},
        {k: v for k, v in _ROOT_RO.items() if k not in {"RW", "Mode"}},
    ],
    ids=["read-write", "rw-unknown"],
)
async def test_a_writable_or_unknown_root_bind_still_blocks_and_names_the_container(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mount: dict[str, object]
) -> None:
    ws = _workspace(base, "ws-under-writable-root", tmp_path)
    _docker_with(monkeypatch, _inspect_doc(mount))
    reclaimer = _reclaimer(base)
    reclaimer.list_containers = stale_dirs.list_containers
    result = await reclaimer.run_once()
    assert _reason(result, "ws-under-writable-root") is RetainedReason.MOUNTED
    [kept] = result.retained
    assert _NODE_EXPORTER in kept.detail
    assert _NODE_EXPORTER_ID[:12] in kept.detail
    assert ws.exists()


@pytest.mark.parametrize("inside", ["", "/repos/app"])
def test_a_read_only_bind_of_the_dir_itself_or_inside_still_blocks(inside: str) -> None:
    """It may be a live reader of in-flight state."""
    source = f"{HOST_BASE}/ws-read{inside}"
    reader = ContainerMounts("reader0000001", (source,), read_only_sources=frozenset({source}))
    assert reader.blocks("ws-read", HOST_BASE)


@pytest.mark.parametrize("ancestor", ["/", "/srv", HOST_BASE])
def test_read_only_ancestors_are_skipped_and_writable_ones_are_not(ancestor: str) -> None:
    read_only = ContainerMounts(
        "ro0000000001", (ancestor,), read_only_sources=frozenset({ancestor})
    )
    writable = ContainerMounts("rw0000000001", (ancestor,))
    assert not read_only.blocks("ws-x", HOST_BASE)
    assert writable.blocks("ws-x", HOST_BASE)


def test_inspect_reads_rw_and_the_name() -> None:
    inspected = parse_inspect(_inspect_doc(_ROOT_RO))
    assert inspected is not None
    assert inspected.name == _NODE_EXPORTER
    assert inspected.read_only_sources == frozenset({"/"})
    unknown = parse_inspect(_inspect_doc({k: v for k, v in _ROOT_RO.items() if k != "RW"}))
    assert unknown is not None
    assert unknown.read_only_sources == frozenset()
    assert parse_inspect(_inspect_doc({**_ROOT_RO, "RW": "maybe"})) is None
