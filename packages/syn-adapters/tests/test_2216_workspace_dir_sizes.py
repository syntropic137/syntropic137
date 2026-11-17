"""A workspace directory is sized by the disk it holds, not by its names (#2216).

``measure_workspace_dir`` once summed ``st_size`` per file name, so a
hard-linked seed cache counted once per link and a sparse file by its length:
/health reported 33 retained directories at ~462 GiB on a 289.6 GiB disk.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends import stale_dirs
from syn_adapters.workspace_backends.stale_dirs import measure_workspace_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.unit

_MIB = 1024 * 1024


def _allocated(path: Path) -> int:
    return path.lstat().st_blocks * 512


def test_a_file_hard_linked_three_times_is_sized_once(tmp_path: Path) -> None:
    ws = tmp_path / "ws-linked"
    cache = ws / "seeds" / "uv"
    cache.mkdir(parents=True)
    (cache / "a").write_bytes(os.urandom(_MIB))
    os.link(cache / "a", cache / "b")
    (ws / "repos").mkdir()
    os.link(cache / "a", ws / "repos" / "c")  # a link in another subdirectory too

    listing = measure_workspace_dir(ws)

    assert listing.size_bytes == _allocated(cache / "a")
    assert listing.unreadable is None


def _walk_then(
    after: Path, change: Callable[[], None]
) -> Callable[
    [Path, Callable[[OSError], object] | None], Iterator[tuple[str, list[str], list[str]]]
]:
    """The real ``os.walk``, in name order, running ``change`` once ``after`` is consumed."""
    real = os.walk

    def walk(
        top: Path, onerror: Callable[[OSError], object] | None = None
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        for dirpath, dirnames, filenames in real(top, onerror=onerror):
            dirnames.sort()
            yield dirpath, dirnames, filenames
            if Path(dirpath) == after:
                change()

    return walk


@pytest.mark.parametrize("transition", ["unlinked", "linked"])
def test_an_inode_whose_link_count_changes_mid_walk_is_sized_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transition: str
) -> None:
    # A live seed cache links and unlinks while the reclaimer walks it: the
    # second name may then report one link (2 -> 1) or the first did (1 -> 2).
    ws = tmp_path / "ws-live-cache"
    first, second = ws / "first", ws / "second"
    first.mkdir(parents=True)
    second.mkdir()
    blob = first / "blob"
    blob.write_bytes(os.urandom(8192))
    expected = _allocated(blob)
    if transition == "unlinked":
        os.link(blob, second / "blob")
        change: Callable[[], None] = blob.unlink
    else:

        def change() -> None:
            os.link(blob, second / "blob")

    monkeypatch.setattr(stale_dirs.os, "walk", _walk_then(first, change))

    listing = measure_workspace_dir(ws)

    assert (second / "blob").exists()  # the change ran, between the two directories
    assert listing.size_bytes == expected
    assert listing.unreadable is None


def test_a_sparse_file_is_sized_by_its_allocated_blocks(tmp_path: Path) -> None:
    ws = tmp_path / "ws-sparse"
    ws.mkdir()
    sparse = ws / "sparse.img"
    with sparse.open("wb") as handle:
        handle.seek(1024 * _MIB)
        handle.write(b"x")
    if _allocated(sparse) >= sparse.stat().st_size:
        pytest.skip("this filesystem allocated every block of the file, so it is not sparse")

    listing = measure_workspace_dir(ws)

    assert listing.size_bytes == _allocated(sparse)
    assert listing.size_bytes < _MIB


def test_a_plain_tree_is_sized_by_the_blocks_its_content_fills(tmp_path: Path) -> None:
    ws = tmp_path / "ws-plain"
    (ws / "repos" / "app").mkdir(parents=True)
    files = {ws / "README.md": 100, ws / "repos" / "app" / "main.py": 10_000}
    for path, length in files.items():
        path.write_bytes(os.urandom(length))
    content = sum(files.values())

    listing = measure_workspace_dir(ws)

    assert listing.size_bytes == sum(_allocated(path) for path in files)
    assert content <= listing.size_bytes <= content + len(files) * 64 * 1024
    assert listing.size_bytes % 512 == 0  # blocks, where the old sum read 10100
    assert listing.unreadable is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory")
def test_an_unreadable_subdirectory_is_still_reported(tmp_path: Path) -> None:
    ws = tmp_path / "ws-locked"
    locked = ws / "locked"
    locked.mkdir(parents=True)
    (locked / "only-copy.md").write_text("unique bytes nobody else holds\n")
    locked.chmod(0)
    try:
        listing = measure_workspace_dir(ws)
    finally:
        locked.chmod(0o700)
    assert listing.unreadable is not None
    assert "PermissionError" in listing.unreadable
