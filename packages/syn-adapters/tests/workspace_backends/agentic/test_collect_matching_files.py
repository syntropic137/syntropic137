"""Artifact collection reads only regular files inside the workspace.

Workspace contents are written by the agent. Collection runs on the host, so
it must not follow a symlink (at the file or at any directory on its path),
must not read anything but a regular file, and must not read an unbounded
number of bytes.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic.adapter_copy import collect_matching_files

if TYPE_CHECKING:
    from pathlib import Path

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
