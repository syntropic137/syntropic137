"""Artifact collection reads only regular files inside the workspace.

Workspace contents are written by the agent. Collection runs on the host, so
it must not follow a symlink (at the file or at any directory on its path),
must not read anything but a regular file, and must not read an unbounded
number of bytes.
"""

from __future__ import annotations

import logging
import os
import stat
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic import workspace_walk
from syn_adapters.workspace_backends.agentic.adapter_copy import (
    MAX_DIRECTORY_ENTRIES,
    _normalize_pattern,
    collect_matching_files,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

_PATTERN = ["artifacts/output/**/*"]
_LIMIT = 1024


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    (ws / "artifacts" / "output").mkdir(parents=True)
    return ws


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    secret = tmp_path / "outside" / "secret.txt"
    secret.parent.mkdir()
    secret.write_bytes(b"outside-bytes")
    return secret


def _collect(ws: Path, patterns: list[str] | None = None) -> list[tuple[str, bytes]]:
    return collect_matching_files(ws, patterns or _PATTERN, max_bytes=_LIMIT)


def test_regular_files_are_collected_unchanged(workspace: Path) -> None:
    out = workspace / "artifacts" / "output"
    (out / "a.md").write_bytes(b"alpha")
    (out / "nested").mkdir()
    (out / "nested" / "b.json").write_bytes(b"{}")

    assert sorted(_collect(workspace)) == [
        ("artifacts/output/a.md", b"alpha"),
        ("artifacts/output/nested/b.json", b"{}"),
    ]


def test_file_symlink_to_outside_is_not_collected(
    workspace: Path, outside: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (workspace / "artifacts" / "output" / "link.md").symlink_to(outside)

    with caplog.at_level(logging.WARNING):
        assert _collect(workspace) == []
    assert "artifacts/output/link.md" in caplog.text
    assert "outside-bytes" not in caplog.text


def test_symlink_inside_root_is_not_collected(workspace: Path) -> None:
    out = workspace / "artifacts" / "output"
    target = workspace / "real.md"
    target.write_bytes(b"in-root")
    (out / "link.md").symlink_to(target)

    assert _collect(workspace) == []


def test_symlinked_directory_on_the_glob_path_is_not_collected(
    workspace: Path, outside: Path
) -> None:
    # Recursive wildcard: a symlinked dir below the literal prefix.
    (workspace / "artifacts" / "output" / "dir").symlink_to(outside.parent)
    assert _collect(workspace) == []
    # Literal component of the pattern is itself a symlinked directory.
    assert _collect(workspace, ["artifacts/output/dir/secret.txt"]) == []
    assert _collect(workspace, ["artifacts/output/dir/*"]) == []


def test_symlinked_literal_prefix_directory_is_not_collected(
    workspace: Path, outside: Path
) -> None:
    out = workspace / "artifacts" / "output"
    out.rmdir()
    out.symlink_to(outside.parent)

    assert _collect(workspace) == []
    assert _collect(workspace, ["artifacts/output/secret.txt"]) == []


def test_oversized_file_is_skipped_with_its_size_logged(
    workspace: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = workspace / "artifacts" / "output"
    (out / "big.bin").write_bytes(b"x" * (_LIMIT + 1))
    (out / "ok.bin").write_bytes(b"x" * _LIMIT)

    with caplog.at_level(logging.WARNING):
        assert _collect(workspace) == [("artifacts/output/ok.bin", b"x" * _LIMIT)]
    assert "artifacts/output/big.bin" in caplog.text
    assert str(_LIMIT + 1) in caplog.text


def test_fifo_is_not_collected_and_does_not_block(workspace: Path) -> None:
    os.mkfifo(workspace / "artifacts" / "output" / "pipe")
    assert _collect(workspace) == []


def test_parent_traversal_in_pattern_is_not_collected(workspace: Path, outside: Path) -> None:
    del outside
    assert _collect(workspace, ["../outside/secret.txt"]) == []


def test_symlinked_workspace_root_itself_is_resolved(workspace: Path, tmp_path: Path) -> None:
    """The root comes from the platform, not the agent, so it may be a link."""
    (workspace / "artifacts" / "output" / "a.md").write_bytes(b"alpha")
    alias = tmp_path / "alias"
    alias.symlink_to(workspace)

    assert _collect(alias) == [("artifacts/output/a.md", b"alpha")]


def test_symlinked_directory_inside_root_is_not_followed(workspace: Path) -> None:
    """No symlinks at all: a directory link that stays inside root is refused too."""
    real_dir = workspace / "elsewhere"
    real_dir.mkdir()
    (real_dir / "c.md").write_bytes(b"in-root")
    (workspace / "artifacts" / "output" / "dir").symlink_to(real_dir)

    assert _collect(workspace, ["artifacts/output/dir/c.md"]) == []


def test_hard_linked_file_is_not_collected(workspace: Path, outside: Path) -> None:
    """A second name for an inode could be one that lives outside the workspace."""
    try:
        os.link(outside, workspace / "artifacts" / "output" / "linked.md")
    except OSError:
        pytest.skip("hard links unsupported across these directories")

    assert _collect(workspace) == []


def test_total_bytes_across_files_are_bounded(workspace: Path) -> None:
    out = workspace / "artifacts" / "output"
    for name in ("a", "b", "c"):
        (out / name).write_bytes(b"x" * 400)

    collected = collect_matching_files(
        workspace, _PATTERN, max_bytes=_LIMIT, max_total_bytes=_LIMIT
    )
    assert len(collected) == 2
    assert sum(len(content) for _, content in collected) <= _LIMIT


def test_number_of_matches_examined_is_bounded(workspace: Path) -> None:
    out = workspace / "artifacts" / "output"
    for i in range(5):
        (out / f"f{i}").write_bytes(b"x")

    collected = collect_matching_files(workspace, _PATTERN, max_bytes=_LIMIT, max_matches=3)
    assert len(collected) == 3


# --- Finding candidates: same selection as Path.glob, bounded cost ---------


def _glob_selection(root: Path, pattern: str) -> set[str]:
    """What the Path.glob implementation selected: its non-directory matches."""
    return {
        str(p.relative_to(root))
        for p in root.glob(_normalize_pattern(pattern))
        if not stat.S_ISDIR(p.lstat().st_mode)
    }


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A workspace with no symlinks, where glob and the walk must agree."""
    ws = tmp_path / "tree"
    for rel in (
        "README.md",
        "top.txt",
        ".hidden.md",
        "artifacts/input/prev.md",
        "artifacts/output/a.md",
        "artifacts/output/b.json",
        "artifacts/output/.dot",
        "artifacts/output/sub/c.md",
        "artifacts/output/sub/deeper/d.txt",
        "artifacts/output/.hiddendir/e.md",
        "artifacts/outputx/f.md",
        "repo/src/g.md",
    ):
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_bytes(rel.encode())
    (ws / "artifacts" / "output" / "empty").mkdir()
    return ws


@pytest.mark.parametrize(
    "pattern",
    [
        "artifacts/output/**/*",  # what ArtifactCollector and AgentExecutionHandler pass
        "/workspace/artifacts/output/**/*",
        "artifacts/output/**",
        "artifacts/output/*",
        "*.md",
        "**/*.md",
        "**/*",
        "**",
        "artifacts/*/*.md",
        "artifacts/output/?.md",
        "artifacts/output/[ab].*",
        "artifacts/output/sub/c.md",
        "artifacts/output/**/deeper/*",
        "artifacts/**/**/*.md",
    ],
)
def test_selection_matches_path_glob(tree: Path, pattern: str) -> None:
    root = tree.resolve()
    collected = {path for path, _ in _collect(tree, [pattern])}
    assert collected == _glob_selection(root, pattern)


def test_several_patterns_select_each_file_once(tree: Path) -> None:
    collected = [path for path, _ in _collect(tree, ["artifacts/output/**/*", "**/*.md"])]
    assert len(collected) == len(set(collected))
    root = tree.resolve()
    assert set(collected) == _glob_selection(root, "artifacts/output/**/*") | _glob_selection(
        root, "**/*.md"
    )


class _EntriesTaken:
    """Wraps os.scandir(fd) to count the entries the walk takes from each listing.

    Listings are identified by the (device, inode) of the directory fd, so the
    spy never turns an fd back into a path: that needs /proc (Linux only) and
    the walk itself never does it either. Stopping at a cap takes one entry
    past it, to learn that the listing was cut short.
    """

    def __init__(self) -> None:
        self._by_inode: dict[tuple[int, int], int] = {}
        self._scandir = os.scandir

    def of(self, directory: Path) -> int:
        """Entries taken from the listing of `directory`; KeyError if never listed."""
        st = directory.lstat()
        return self._by_inode[(st.st_dev, st.st_ino)]

    def was_listed(self, directory: Path) -> bool:
        st = directory.lstat()
        return (st.st_dev, st.st_ino) in self._by_inode

    @property
    def total(self) -> int:
        return sum(self._by_inode.values())

    @contextmanager
    def __call__(self, fd: int) -> Iterator[Iterator[os.DirEntry[str]]]:
        st = os.fstat(fd)
        key = (st.st_dev, st.st_ino)
        self._by_inode[key] = 0
        with self._scandir(fd) as listing:
            yield self._count(key, listing)

    def _count(
        self, key: tuple[int, int], listing: Iterator[os.DirEntry[str]]
    ) -> Iterator[os.DirEntry[str]]:
        for entry in listing:
            self._by_inode[key] += 1
            yield entry


@pytest.fixture
def entries_taken(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> _EntriesTaken:
    taken = _EntriesTaken()
    monkeypatch.setattr(workspace_walk.os, "scandir", taken)
    return taken


def test_huge_directory_is_listed_only_up_to_the_cap(
    workspace: Path, entries_taken: _EntriesTaken, caplog: pytest.LogCaptureFixture
) -> None:
    out = workspace / "artifacts" / "output"
    (out / "a.md").write_bytes(b"alpha")
    big = out / "big"
    big.mkdir()
    for i in range(50_000):
        os.close(os.open(big / f"f{i}", os.O_CREAT | os.O_WRONLY, 0o600))

    tracemalloc.start()
    started = time.monotonic()
    try:
        with caplog.at_level(logging.WARNING):
            # The total cap (default 100k) is above the 50k entries here, so
            # only the per-directory cap can stop the listing.
            collected = collect_matching_files(
                workspace, ["artifacts/output/**/*.md"], max_bytes=_LIMIT
            )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert collected == [("artifacts/output/a.md", b"alpha")]
    assert entries_taken.of(big) == MAX_DIRECTORY_ENTRIES + 1
    assert f"Stopped listing artifacts/output/big after {MAX_DIRECTORY_ENTRIES} entries" in (
        caplog.text
    )
    # Path.glob holds the whole 50k-entry listing (about 9 MB) before
    # yielding anything; the walk holds one entry at a time.
    assert peak < 1024 * 1024
    assert time.monotonic() - started < 30


def test_every_directory_is_listed_only_up_to_the_cap(
    workspace: Path, entries_taken: _EntriesTaken, caplog: pytest.LogCaptureFixture
) -> None:
    out = workspace / "artifacts" / "output"
    for d in range(4):
        (out / f"d{d}").mkdir()
        for i in range(20):
            (out / f"d{d}" / f"f{i}.txt").write_bytes(b"x")

    with caplog.at_level(logging.WARNING):
        collect_matching_files(
            workspace,
            ["artifacts/output/**/*.md"],
            max_bytes=_LIMIT,
            max_directory_entries=8,
            max_entries=1_000,
        )

    for d in range(4):
        assert entries_taken.of(out / f"d{d}") == 8 + 1
        assert f"Stopped listing artifacts/output/d{d} after 8 entries" in caplog.text


def test_entries_examined_across_directories_are_bounded(
    workspace: Path, entries_taken: _EntriesTaken, caplog: pytest.LogCaptureFixture
) -> None:
    out = workspace / "artifacts" / "output"
    for d in range(4):
        (out / f"d{d}").mkdir()
        for i in range(5):
            (out / f"d{d}" / f"f{i}.txt").write_bytes(b"x")

    with caplog.at_level(logging.WARNING):
        collected = collect_matching_files(
            workspace,
            ["artifacts/output/**/*.md"],
            max_bytes=_LIMIT,
            max_entries=12,
            max_directory_entries=1_000,
        )

    assert collected == []
    # 3 entries lead down to the first d* directory (5 entries), 1 more to
    # the second, so the cap falls inside the second one listed and the last
    # two are never opened.
    assert entries_taken.total == 12 + 1
    assert sum(entries_taken.was_listed(out / f"d{d}") for d in range(4)) == 2
    assert "Stopped after examining 12 entries" in caplog.text
    assert "Stopped listing" not in caplog.text


def test_symlinked_prefix_directory_is_not_listed(
    workspace: Path, outside: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Names outside the workspace are never listed, so never even logged."""
    out = workspace / "artifacts" / "output"
    out.rmdir()
    out.symlink_to(outside.parent)

    with caplog.at_level(logging.DEBUG):
        assert _collect(workspace) == []
        assert _collect(workspace, ["artifacts/output/*"]) == []
    assert "secret.txt" not in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_walk_relies_only_on_posix_fd_primitives() -> None:
    """The walk lists by fd and opens children by dir_fd, never via /proc.

    Both primitives exist on Linux and macOS. This suite runs on both, so a
    Linux-only construct (such as resolving an fd through /proc/self/fd)
    fails here on a developer Mac rather than only in production.
    """
    assert os.scandir in os.supports_fd
    assert os.open in os.supports_dir_fd
    source = Path(workspace_walk.__file__).read_text()
    assert "/proc" not in source


def test_deep_directory_chain_opens_each_directory_once(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each directory is opened from its parent's fd, never re-walked from the root.

    Reopening every ancestor would cost depth^2 opens for a chain the agent
    can make as deep as it likes.
    """
    depth = 40
    chain = workspace / "artifacts" / "output"
    for i in range(depth):
        chain /= f"c{i}"
    chain.mkdir(parents=True)
    (chain / "deep.md").write_bytes(b"deep")

    opens = 0
    real_open = os.open

    def counting_open(*args: object, **kwargs: object) -> int:
        nonlocal opens
        opens += 1
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(workspace_walk.os, "open", counting_open)
    collected = collect_matching_files(workspace, ["**/*.md"], max_bytes=_LIMIT)

    assert [path for path, _ in collected] == [
        "/".join(("artifacts", "output", *(f"c{i}" for i in range(depth)), "deep.md"))
    ]
    directories = depth + 3  # root, artifacts, output, then the chain
    # One open per directory for the walk, plus one walk from the root (a
    # directory each, then the file) to read the single matched file.
    assert opens <= 2 * directories + 1


def test_walk_goes_no_deeper_than_the_depth_cap(
    workspace: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = workspace / "artifacts" / "output"
    (out / "shallow.md").write_bytes(b"s")
    deep = out / "x" / "y"
    deep.mkdir(parents=True)
    (deep / "deep.md").write_bytes(b"d")

    with caplog.at_level(logging.WARNING):
        collected = collect_matching_files(workspace, ["**/*.md"], max_bytes=_LIMIT, max_depth=3)

    # artifacts/output/x is 3 deep and entered; artifacts/output/x/y is 4.
    assert collected == [("artifacts/output/shallow.md", b"s")]
    assert "Did not enter artifacts/output/x/y: deeper than 3 directories" in caplog.text
