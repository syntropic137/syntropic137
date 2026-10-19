"""Deleting a proven workspace directory: authorization, the mark, the delete (#1983).

THE NAME IS NOT THE AUTHORIZATION. A directory renamed ``.deleting-<id>``
is being deleted, and a pass (or the first after a restart) finishes it
without judging it again. A name anyone could have given a directory cannot
carry that weight, so the authorization is a record the reclaimer writes
BEFORE the rename, outside every workspace tree (``<base>/.syn-reclaim-auth``,
which no workspace container binds and the scan never lists), bound to the
directory's ``(st_dev, st_ino)``. A ``.deleting-`` directory with no record,
or whose identity is not the recorded one, is not deleted.

THE DELETE NEVER FOLLOWS A PATH. Every step is descriptor-relative: each
directory is opened ``O_NOFOLLOW | O_DIRECTORY`` relative to its parent's
descriptor and checked by ``fstat``, entries are unlinked by name relative to
that descriptor, and nothing crosses a mount (``st_dev``). A directory swapped
for a symlink mid-delete fails to open, or is unlinked as the link it now is;
nothing outside the tree is reached.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: A directory claimed for a second look is renamed to this prefix plus its
#: workspace id, so no owner can reach it at its workspace path any more.
CLAIM_PREFIX = ".reclaiming-"

#: A directory authorized for deletion and being deleted.
DELETE_PREFIX = ".deleting-"

#: Where deletion authorizations live, directly under the workspace base.
AUTH_DIRNAME = ".syn-reclaim-auth"

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


class ReclaimIdentityError(OSError):
    """The directory at a reclaim path is not the one that was judged."""


class DeletionAuthorization(BaseModel):
    """The reclaimer's record that one directory was proven lossless."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    st_dev: int
    st_ino: int
    authorized_at: float

    @property
    def identity(self) -> tuple[int, int]:
        return (self.st_dev, self.st_ino)


def is_being_deleted(host_dir: str) -> bool:
    return Path(host_dir).name.startswith(DELETE_PREFIX)


def _identity(path: Path) -> tuple[int, int]:
    found = path.lstat()
    if not stat.S_ISDIR(found.st_mode):
        raise ReclaimIdentityError(errno.ENOTDIR, "not a directory (or a symlink)", str(path))
    return (found.st_dev, found.st_ino)


def _auth_path(base: Path, workspace_id: str) -> Path:
    return base / AUTH_DIRNAME / f"{workspace_id}.json"


def authorize_and_mark(
    claimed: str, workspace_id: str, identity: tuple[int, int], *, now: float
) -> str:
    """Record the authorization, then rename the claimed directory to its deleting name.

    Raises `ReclaimIdentityError` unless ``claimed`` is still the judged
    directory, before and after the rename. The record is durable (fsync)
    before the rename, so a crash between them leaves a claim, not an
    unauthorized ``.deleting-`` directory.
    """
    path = Path(claimed)
    if not path.name.startswith(CLAIM_PREFIX) or _identity(path) != identity:
        raise ReclaimIdentityError(errno.ESTALE, "not the directory that was judged", claimed)
    deleting = path.with_name(DELETE_PREFIX + workspace_id)
    if os.path.lexists(deleting):
        raise FileExistsError(errno.EEXIST, "already exists", str(deleting))
    record = DeletionAuthorization(
        workspace_id=workspace_id, st_dev=identity[0], st_ino=identity[1], authorized_at=now
    )
    _write_record(_auth_path(path.parent, workspace_id), record)
    path.rename(deleting)
    if _identity(deleting) != identity:
        raise ReclaimIdentityError(errno.ESTALE, "replaced during the rename", str(deleting))
    return str(deleting)


def _write_record(target: Path, record: DeletionAuthorization) -> None:
    target.parent.mkdir(mode=0o700, exist_ok=True)
    staged = target.with_suffix(".tmp")
    with staged.open("w") as out:
        out.write(record.model_dump_json())
        out.flush()
        os.fsync(out.fileno())
    staged.replace(target)
    directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def authorized_identity(deleting: str) -> tuple[int, int] | None:
    """The identity a ``.deleting-`` directory was authorized under, if it is still it.

    None when there is no record, the record is unreadable, or the directory
    there now is another one (replaced, forged, or a symlink).
    """
    path = Path(deleting)
    workspace_id = path.name.removeprefix(DELETE_PREFIX)
    try:
        record = DeletionAuthorization.model_validate_json(
            _auth_path(path.parent, workspace_id).read_text()
        )
        current = _identity(path)
    except (OSError, ValidationError, json.JSONDecodeError):
        return None
    if record.workspace_id != workspace_id or record.identity != current:
        return None
    return current


def forget_authorization(base: str, workspace_id: str) -> None:
    """Drop a record whose directory is gone, and the records directory once empty."""
    record = _auth_path(Path(base), workspace_id)
    os.unlink(record)  # noqa: PTH108
    with contextlib.suppress(OSError):  # not empty: another delete is in progress
        os.rmdir(record.parent)  # noqa: PTH106


def _scandir(fd: int) -> Iterator[os.DirEntry[str]]:
    """Entries of the directory open at ``fd``. A seam for the swap-during-delete test."""
    with os.scandir(fd) as entries:
        yield from list(entries)


def delete_tree_until(
    path: str, identity: tuple[int, int], deadline: float, clock: Callable[[], float]
) -> bool:
    """Delete the ``.deleting-`` tree at ``path`` until ``clock() >= deadline``.

    True when it is gone; False when time ran out, leaving the rest under the
    same name for the next pass. Raises ``OSError`` for anything it cannot
    delete or that is not what was authorized. Blocking: run it off the loop.
    """
    target = Path(path)
    if not target.name.startswith(DELETE_PREFIX):
        raise ValueError(f"refusing to delete {path}: not a directory marked for deletion")
    parent_fd = os.open(target.parent, _DIR_FLAGS)
    try:
        root_fd = os.open(target.name, _DIR_FLAGS, dir_fd=parent_fd)
        try:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != identity:
                raise ReclaimIdentityError(errno.ESTALE, "not the authorized directory", path)
            if not _empty(root_fd, opened.st_dev, deadline, clock):
                return False
        finally:
            os.close(root_fd)
        now = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        if (now.st_dev, now.st_ino) != identity:
            raise ReclaimIdentityError(errno.ESTALE, "replaced while it was emptied", path)
        os.rmdir(target.name, dir_fd=parent_fd)
        return True
    finally:
        os.close(parent_fd)


def _empty(fd: int, device: int, deadline: float, clock: Callable[[], float]) -> bool:
    """Delete everything inside the directory at ``fd``; False when out of time."""
    for entry in _scandir(fd):
        name = entry.name
        found = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(found.st_mode):
            if not _empty_subdirectory(fd, name, found, device, deadline, clock):
                return False
        else:
            # Never follows: a symlink is removed as a link.
            os.unlink(name, dir_fd=fd)
        if clock() >= deadline:
            return False
    return True


def _empty_subdirectory(
    fd: int,
    name: str,
    found: os.stat_result,
    device: int,
    deadline: float,
    clock: Callable[[], float],
) -> bool:
    if found.st_dev != device:
        raise OSError(errno.EXDEV, "a mount point inside the tree", name)
    # O_NOFOLLOW: a directory swapped for a symlink since the stat fails here.
    sub = os.open(name, _DIR_FLAGS, dir_fd=fd)
    try:
        opened = os.fstat(sub)
        if (opened.st_dev, opened.st_ino) != (found.st_dev, found.st_ino):
            raise ReclaimIdentityError(errno.ESTALE, "replaced between stat and open", name)
        if not _empty(sub, device, deadline, clock):
            return False
    finally:
        os.close(sub)
    # A symlink or a non-empty directory swapped in now fails (ENOTDIR, ENOTEMPTY).
    os.rmdir(name, dir_fd=fd)
    return True
