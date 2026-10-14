#!/usr/bin/env python3
"""Host side of ``just selfhost-backup`` and ``just selfhost-restore``.

The backup itself (dump, verify, prune, restore into a staging database and
swap) is ``docker/db-backup/syn-db-backup.sh``, which runs inside the
``db-backup`` service. This program is what runs on the host around it:

``backup``
    Run the same ``backup`` command the scheduled service runs, as the
    database identity the running ``timescaledb`` container reports, and print
    host paths instead of container paths.

``restore FILE [ARGS...]``
    Refuse while executions are in flight (``predeploy_check.py ARGS``; a
    restore discards running executions too), stop the writers, restore FILE,
    and start the writers again unless the restore itself failed.

The database's identity (user and database name, never the password) comes
from the running container, not from ``infra/.env``, which can have changed
since the container was created. FILE and ARGS only ever travel as argv, so a
file name is data, never shell.

Exit codes: whatever the step that failed returned; 1 when timescaledb is not
running or FILE does not exist; 3 when the script refused a populated database
without ``--force`` (the writers are started again, nothing changed).
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: The services that write to the database. The same set
#: docs/deployment/timescaledb-2.29-upgrade.md stops before its backup,
#: because they reconnect and write the moment Postgres is reachable.
WRITERS: tuple[str, ...] = ("api", "collector", "event-store", "gateway")

#: Where the db-backup service mounts BACKUP_DIR, and BACKUP_DIR's default.
CONTAINER_BACKUP_DIR = "/backups"
DEFAULT_BACKUP_DIR = "/var/backups/syn"

#: syn-db-backup.sh's exit code for "populated database, no --force": nothing
#: was changed, so the writers go back up.
EXIT_REFUSED_UNCHANGED = 3

FORCE = "--force"
_PREDEPLOY_CHECK = Path(__file__).resolve().parent / "predeploy_check.py"


class TimescaleNotRunningError(Exception):
    """The timescaledb container could not report its identity."""


@dataclass(frozen=True)
class DbIdentity:
    """The user and database the running timescaledb container was created with."""

    user: str
    database: str

    def env_args(self) -> list[str]:
        return ["-e", f"PGUSER={self.user}", "-e", f"PGDATABASE={self.database}"]


@dataclass(frozen=True)
class Compose:
    """``docker compose`` with the selfhost files, as the justfile spells it."""

    prefix: tuple[str, ...]

    def argv(self, *args: str) -> list[str]:
        return [*self.prefix, *args]

    def run(self, *args: str) -> int:
        return subprocess.run(self.argv(*args), check=False).returncode

    def output(self, *args: str) -> str:
        """stdout of a command that must succeed; raises CalledProcessError."""
        return subprocess.run(
            self.argv(*args), check=True, stdout=subprocess.PIPE, text=True
        ).stdout.strip()


def db_identity(compose: Compose) -> DbIdentity:
    """Read only POSTGRES_USER and POSTGRES_DB from the running container."""
    try:
        user = compose.output("exec", "-T", "timescaledb", "printenv", "POSTGRES_USER")
        database = compose.output("exec", "-T", "timescaledb", "printenv", "POSTGRES_DB")
    except subprocess.CalledProcessError as exc:
        raise TimescaleNotRunningError from exc
    if not user or not database:
        raise TimescaleNotRunningError
    return DbIdentity(user=user, database=database)


def host_path_line(line: str, backup_dir: str) -> str:
    """Rewrite the container's /backups/ paths to where they are on the host."""
    return line.replace(f"{CONTAINER_BACKUP_DIR}/", f"{backup_dir.rstrip('/')}/")


def backup(compose: Compose, backup_dir: str) -> int:
    identity = db_identity(compose)
    argv = compose.argv(
        "run", "--rm", "--no-TTY", *identity.env_args(), "db-backup", "backup", CONTAINER_BACKUP_DIR
    )
    with subprocess.Popen(argv, stdout=subprocess.PIPE, text=True) as proc:
        assert proc.stdout is not None  # stdout=PIPE
        for line in proc.stdout:
            sys.stdout.write(host_path_line(line, backup_dir))
            sys.stdout.flush()
    return proc.returncode


def run_predeploy_check(args: Sequence[str]) -> int:
    return subprocess.run([sys.executable, str(_PREDEPLOY_CHECK), *args], check=False).returncode


def restore(
    compose: Compose,
    file: str,
    args: Sequence[str],
    predeploy_check: Callable[[Sequence[str]], int] = run_predeploy_check,
) -> int:
    given = Path(file)
    if not given.is_file():
        print(f"❌ No such backup: {file}")
        return 1
    directory = given.parent.resolve()
    name = given.name

    rc = predeploy_check(args)
    if rc != 0:
        return rc

    force = [FORCE] if FORCE in args else []
    identity = db_identity(compose)
    writers = " ".join(WRITERS)
    print(f"Stopping writers: {writers}", flush=True)
    rc = compose.run("stop", *WRITERS)
    if rc != 0:
        return rc

    rc = compose.run(
        "run",
        "--rm",
        "--no-TTY",
        *identity.env_args(),
        "-v",
        f"{directory}:/restore:ro",
        "db-backup",
        "restore",
        f"/restore/{name}",
        *force,
    )
    if rc not in (0, EXIT_REFUSED_UNCHANGED):
        print(
            f"❌ Restore failed (exit {rc}); the database was not replaced. Writers left STOPPED:"
        )
        print(f"   {shlex.join(compose.argv('start', *WRITERS))}")
        return rc

    print(f"Starting writers: {writers}", flush=True)
    start_rc = compose.run("start", *WRITERS)
    if start_rc != 0:
        return start_rc
    if rc == 0:
        # The restore paused admission inside the restored data, so the API
        # comes up refusing new starts and re-offers no queued work (#1387).
        print(
            "⏸️  Execution admission is PAUSED: queued and paused work from the backup will not start."
        )
        print(
            "   Review it, then resume with PUT /api/v1/maintenance "
            '{"active": false, "reason": "", "actor": "<you>"}'
        )
    return rc


def main(
    argv: Sequence[str] | None = None,
    predeploy_check: Callable[[Sequence[str]], int] = run_predeploy_check,
) -> int:
    parser = argparse.ArgumentParser(
        description="Host side of just selfhost-backup and selfhost-restore."
    )
    parser.add_argument(
        "--compose", required=True, help="the docker compose command, e.g. the justfile's"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup")
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("file")
    restore_parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    command: str = ns.command
    compose = Compose(prefix=tuple(shlex.split(str(ns.compose))))
    try:
        if command == "backup":
            return backup(compose, os.environ.get("BACKUP_DIR") or DEFAULT_BACKUP_DIR)
        rest: list[str] = [str(a) for a in ns.args]
        return restore(compose, str(ns.file), rest, predeploy_check)
    except TimescaleNotRunningError:
        print("❌ timescaledb is not running")
        return 1


if __name__ == "__main__":
    sys.exit(main())
