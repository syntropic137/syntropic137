"""The self-host database backup: naming, verification, retention, schedule.

``docker/db-backup/syn-db-backup.sh`` is the one implementation behind
``just selfhost-backup``, ``just selfhost-restore`` and the scheduled
``db-backup`` service. These tests run the real script with stand-in
``pg_dump`` / ``pg_restore`` on PATH, so they need no database. The
round trip through a real TimescaleDB, hypertables included, is
``test_db_backup_integration.py``.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "docker" / "db-backup" / "syn-db-backup.sh"
_SELFHOST = _ROOT / "docker" / "docker-compose.selfhost.yaml"
_BASE = _ROOT / "docker" / "docker-compose.yaml"

_DAY = 86400
_LEDGER = ".syn-db-backup.ledger"

#: A real `pg_restore --list` excerpt: two TABLE DATA entries among others.
_LISTING_WITH_DATA = """\
;
; Archive created at 2026-10-08 03:00:01 UTC
;
5; 2615 16386 SCHEMA - event_store syn
241; 1259 16400 TABLE public events syn
3401; 0 16400 TABLE DATA public events syn
3402; 0 16420 TABLE DATA public agent_events syn
"""
_LISTING_WITHOUT_DATA = """\
5; 2615 16386 SCHEMA - event_store syn
241; 1259 16400 TABLE public events syn
"""
#: `pg_restore --data-only` of an archive matching _LISTING_WITH_DATA.
_DATA_STREAM = '''\
--
-- PostgreSQL database dump
--
SET statement_timeout = 0;

COPY public.events (global_nonce, payload) FROM stdin;
1\t{"n": 1}
2\t{"n": 2}
3\t{"n": 3}
\\.


COPY public."Agent Events" ("time", "odd ""col""") FROM stdin;
2026-10-01 00:00:00+00\tx
\\.

'''


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def fake_pg(tmp_path: Path):
    """PATH with pg_dump writing a file and pg_restore reading LISTING / DATA back."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "pg_dump",
        'for a in "$@"; do case $a in'
        ' --file=*) echo "${DUMP_PAYLOAD:-archive}" > "${a#--file=}";; esac; done',
    )

    def configure(
        listing: str | None, data: str = _DATA_STREAM, data_exit: int = 0
    ) -> dict[str, str]:
        if listing is None:
            _stub(
                bin_dir,
                "pg_restore",
                'echo "pg_restore: error: input file is too short" >&2; exit 1',
            )
        else:
            (tmp_path / "listing").write_text(listing)
            (tmp_path / "data").write_text(data)
            _stub(
                bin_dir,
                "pg_restore",
                'case "$*" in\n'
                f'  *--list*) cat "{tmp_path / "listing"}" ;;\n'
                f'  *--data-only*) cat "{tmp_path / "data"}"; exit {data_exit} ;;\n'
                "  *) exit 64 ;;\n"
                "esac",
            )
        return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    return configure


def _published(directory: Path) -> list[Path]:
    """Everything in DIRECTORY but the ledger, which every backup appends to."""
    return [p for p in directory.iterdir() if p.name != _LEDGER]


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
    )


class TestBackup:
    def test_verified_dump_is_kept_under_a_timestamped_name(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        result = _run("backup", str(out), env=fake_pg(_LISTING_WITH_DATA))

        assert result.returncode == 0, result.stderr
        files = sorted(p.name for p in _published(out))
        assert len(files) == 2
        assert re.fullmatch(r"syn-\d{8}T\d{6}Z\.dump", files[0]), files
        assert files[1] == f"{files[0]}.manifest"
        assert f"backup ok: {out}/{files[0]}" in result.stdout
        assert "2 tables, 4 rows" in result.stdout
        # A dump holds every event: never world- or group-readable.
        for name in files:
            assert stat.S_IMODE((out / name).stat().st_mode) == 0o600

    def test_manifest_records_the_checksum_and_every_tables_rows(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        assert _run("backup", str(out), env=fake_pg(_LISTING_WITH_DATA)).returncode == 0
        dump = next(out.glob("syn-*.dump"))
        manifest = (out / f"{dump.name}.manifest").read_text().splitlines()

        assert manifest == [
            "syn-db-backup manifest 1",
            f"sha256 {hashlib.sha256(dump.read_bytes()).hexdigest()}",
            "rows 3 public.events",
            'rows 1 public."Agent Events"',
            "tables 2",
        ]

    @pytest.mark.parametrize(
        ("data", "data_exit", "why"),
        [
            # Cut inside a COPY block: the terminator never arrives.
            (_DATA_STREAM.split("2\t")[0], 0, "cut inside the data"),
            # pg_restore itself reports the archive unreadable part way.
            (_DATA_STREAM, 1, "pg_restore failed reading the data"),
            # The TOC lists two tables, the data holds one.
            (_DATA_STREAM.split('COPY public."Agent')[0], 0, "a listed table has no data"),
        ],
        ids=["cut-inside-copy", "pg-restore-fails", "table-missing"],
    )
    def test_archive_whose_rows_do_not_read_back_is_not_kept(
        self, tmp_path, fake_pg, data, data_exit, why
    ):
        out = tmp_path / "backups"
        out.mkdir()
        result = _run("backup", str(out), env=fake_pg(_LISTING_WITH_DATA, data, data_exit))

        assert result.returncode != 0, why
        assert "refusing to keep it" in result.stderr, why
        assert _published(out) == [], f"{why}: a failed backup must leave nothing behind"

    def test_archive_without_table_data_is_not_kept(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        result = _run("backup", str(out), env=fake_pg(_LISTING_WITHOUT_DATA))

        assert result.returncode != 0
        assert "no table data" in result.stderr
        assert _published(out) == [], "a failed backup must leave nothing behind"

    def test_unreadable_archive_is_not_kept(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        result = _run("backup", str(out), env=fake_pg(None))

        assert result.returncode != 0
        assert "cannot read" in result.stderr
        assert _published(out) == []

    def test_missing_directory_fails_rather_than_dumping_elsewhere(self, tmp_path, fake_pg):
        result = _run("backup", str(tmp_path / "absent"), env=fake_pg(_LISTING_WITH_DATA))
        assert result.returncode != 0
        assert "does not exist" in result.stderr

    def test_same_second_backups_each_keep_their_own_archive(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        bin_dir = tmp_path / "bin"
        # Freeze the clock: both backups get the same second.
        _stub(bin_dir, "date", "echo 20261008T030000Z")
        env = fake_pg(_LISTING_WITH_DATA)

        first = _run("backup", str(out), env={**env, "DUMP_PAYLOAD": "first-archive"})
        second = _run("backup", str(out), env={**env, "DUMP_PAYLOAD": "second-archive"})

        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        first_path = first.stdout.split("backup ok: ")[1].split(" (")[0]
        second_path = second.stdout.split("backup ok: ")[1].split(" (")[0]
        assert first_path != second_path
        assert Path(first_path).read_text() == "first-archive\n"
        assert Path(second_path).read_text() == "second-archive\n"
        assert sorted(p.name for p in _published(out)) == [
            "syn-20261008T030000Z-1.dump",
            "syn-20261008T030000Z-1.dump.manifest",
            "syn-20261008T030000Z.dump",
            "syn-20261008T030000Z.dump.manifest",
        ]

    @pytest.mark.parametrize(
        "occupant",
        ["directory", "symlink-to-directory", "dangling-symlink", "symlink-to-file"],
    )
    @pytest.mark.parametrize(
        "where", ["syn-20261008T030000Z.dump", "syn-20261008T030000Z.dump.manifest"]
    )
    def test_publishing_never_replaces_or_enters_what_holds_the_name(
        self, tmp_path, fake_pg, occupant, where
    ):
        out = tmp_path / "backups"
        out.mkdir()
        _stub(tmp_path / "bin", "date", "echo 20261008T030000Z")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep").write_text("operator data")
        taken = out / where
        if occupant == "directory":
            taken.mkdir()
            (taken / "keep").write_text("operator data")
        elif occupant == "symlink-to-directory":
            taken.symlink_to(elsewhere)
        elif occupant == "dangling-symlink":
            taken.symlink_to(tmp_path / "nowhere")
        else:
            taken.symlink_to(elsewhere / "keep")

        def snapshot() -> list[str]:
            return sorted(str(p) for d in (out, elsewhere) for p in d.rglob("*"))

        env = fake_pg(_LISTING_WITH_DATA)
        before = snapshot()

        result = _run("backup", str(out), env=env)

        assert result.returncode == 0, result.stderr
        assert "syn-20261008T030000Z-1.dump " in result.stdout
        after = snapshot()
        added = sorted(set(after) - set(before))
        assert added == [
            str(out / _LEDGER),
            str(out / "syn-20261008T030000Z-1.dump"),
            str(out / "syn-20261008T030000Z-1.dump.manifest"),
        ], "published into, or beside, what held the name"
        assert set(before) <= set(after)
        assert (elsewhere / "keep").read_text() == "operator data"
        assert taken.is_symlink() == (occupant != "directory")

    def test_a_directory_appearing_at_the_name_mid_publish_is_left_alone(self, tmp_path, fake_pg):
        """The check-then-link race: ln itself finds a directory there."""
        out = tmp_path / "backups"
        out.mkdir()
        bin_dir = tmp_path / "bin"
        _stub(bin_dir, "date", "echo 20261008T030000Z")
        real_ln = shutil.which("ln")
        racer = out / "syn-20261008T030000Z.dump.manifest"
        _stub(bin_dir, "ln", f'[ "$2" = "{racer}" ] && mkdir "$2"\nexec {real_ln} "$@"')

        result = _run("backup", str(out), env=fake_pg(_LISTING_WITH_DATA))

        assert result.returncode == 0, result.stderr
        assert racer.is_dir()
        assert list(racer.iterdir()) == [], "left a link inside a directory it did not create"
        assert (out / "syn-20261008T030000Z-1.dump").is_file()

    @pytest.mark.parametrize("kind", ["symlink-to-file", "dangling-symlink", "directory"])
    def test_ledger_is_never_written_through_what_holds_its_name(self, tmp_path, fake_pg, kind):
        out = tmp_path / "backups"
        out.mkdir()
        target = tmp_path / "operator.conf"
        target.write_text("operator data\n")
        ledger = out / _LEDGER
        if kind == "symlink-to-file":
            ledger.symlink_to(target)
        elif kind == "dangling-symlink":
            ledger.symlink_to(tmp_path / "nowhere")
        else:
            ledger.mkdir()

        result = _run("backup", str(out), env=fake_pg(_LISTING_WITH_DATA))

        assert result.returncode == 0, result.stderr
        assert "will never be pruned" in result.stderr
        assert target.read_text() == "operator data\n"
        assert not (tmp_path / "nowhere").exists()
        assert ledger.is_symlink() == (kind != "directory")

    @pytest.mark.parametrize("dump_ok", [True, False], ids=["backup-ok", "backup-fails"])
    def test_temp_files_live_in_a_private_directory_it_removes(self, tmp_path, fake_pg, dump_ok):
        out = tmp_path / "backups"
        out.mkdir()
        # Anything else in DIR, even named like a temp file, is never cleaned up.
        foreign = out / ".syn-20261008T030000Z.dump.partial.Ab12Cd"
        foreign.write_text("operator data")
        env = fake_pg(_LISTING_WITH_DATA)
        seen = tmp_path / "seen"
        _stub(
            Path(env["PATH"].split(os.pathsep)[0]),
            "pg_dump",
            'for a in "$@"; do case $a in --file=*) f=${a#--file=};; esac; done\n'
            f'ls -ld "$(dirname "$f")" > "{seen}"\n'
            f'echo "$(dirname "$f")" >> "{seen}"\n'
            'echo archive > "$f"\n'
            f"exit {0 if dump_ok else 1}",
        )

        result = _run("backup", str(out), env=env)

        assert (result.returncode == 0) == dump_ok, result.stderr
        mode, work = seen.read_text().splitlines()
        assert mode.startswith("drwx------"), mode
        assert Path(work).parent == out
        assert not Path(work).exists(), "temp directory left behind"
        assert foreign.read_text() == "operator data"

    def test_simultaneous_backups_each_keep_their_own_archive(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        _stub(tmp_path / "bin", "date", "echo 20261008T030000Z")
        env = fake_pg(_LISTING_WITH_DATA)
        procs = [
            subprocess.Popen(
                ["sh", str(_SCRIPT), "backup", str(out)],
                env={**env, "DUMP_PAYLOAD": f"archive-{i}"},
                stdout=subprocess.PIPE,
                text=True,
            )
            for i in range(4)
        ]
        assert [p.wait(timeout=30) for p in procs] == [0, 0, 0, 0]
        payloads = sorted(p.read_text() for p in out.glob("*.dump"))
        assert payloads == [f"archive-{i}\n" for i in range(4)]
        # Each dump has the manifest of its own bytes.
        for dump in out.glob("*.dump"):
            manifest = (out / f"{dump.name}.manifest").read_text()
            assert f"sha256 {hashlib.sha256(dump.read_bytes()).hexdigest()}" in manifest


def _age(path: Path, age_seconds: float) -> None:
    then = time.time() - age_seconds
    os.utime(path, (then, then), follow_symlinks=False)


class TestPrune:
    @staticmethod
    def _make(directory: Path, name: str, age_seconds: float, *, tracked: bool = True) -> Path:
        """A file aged AGE_SECONDS; TRACKED records it in the ledger as backup does."""
        path = directory / name
        path.write_text("x")
        _age(path, age_seconds)
        if tracked:
            # Temp files are recorded before their content exists; published
            # files with the sha256 of their final content.
            digest = "-" if name.startswith(".") else hashlib.sha256(b"x").hexdigest()
            with (directory / _LEDGER).open("a") as ledger:
                ledger.write(f"{path.stat().st_ino} {digest} {name}\n")
        return path

    def test_deletes_only_backups_older_than_retention(self, tmp_path):
        old = self._make(tmp_path, "syn-20260901T030000Z.dump", 8 * _DAY)
        # -mtime +7 would keep this one (it truncates to 7 whole days).
        just_over = self._make(tmp_path, "syn-20260930T030000Z.dump", 7 * _DAY + 120)
        recent = self._make(tmp_path, "syn-20261005T030000Z.dump", 6 * _DAY)
        foreign = self._make(tmp_path, "operator-notes.dump", 30 * _DAY)

        result = _run("prune", str(tmp_path), "7")

        assert result.returncode == 0, result.stderr
        assert not old.exists()
        assert not just_over.exists()
        assert recent.exists()
        assert foreign.exists(), "prune must only touch files it named itself"
        assert f"pruned: {old.name}" in result.stdout

    def test_never_prunes_temp_files_even_when_recorded(self, tmp_path):
        """Temp content is never final, so ownership cannot be proven: left for a human."""
        recorded = self._make(tmp_path, ".syn-20260901T030000Z.dump.partial.Ab12Cd", 365 * _DAY)
        abandoned = tmp_path / ".syn-20260901T030000Z.backup.Ef34Gh"
        abandoned.mkdir()
        (abandoned / "dump").write_text("half a dump")
        _age(abandoned / "dump", 365 * _DAY)
        _age(abandoned, 365 * _DAY)

        assert _run("prune", str(tmp_path), "1").returncode == 0
        assert recorded.exists()
        assert (abandoned / "dump").exists()

    def test_manifests_and_suffixed_backups_age_out_with_the_rest(self, tmp_path):
        old = [
            self._make(tmp_path, name, 8 * _DAY)
            for name in (
                "syn-20260901T030000Z.dump.manifest",
                "syn-20260901T030000Z-1.dump",
                "syn-20260901T030000Z-1.dump.manifest",
                "syn-20260901T030000Z-42.dump",
            )
        ]
        assert _run("prune", str(tmp_path), "7").returncode == 0
        assert not [p for p in old if p.exists()]

    @pytest.mark.parametrize(
        "name",
        [
            # Named like a backup, but not by this script.
            "syn-manual.dump",
            "syn-latest.dump",
            "syn-20260901T030000Z.dump.bak",
            "syn-20260901T030000Z.dump.manifest.old",
            "syn-20260901T030000Z-0.dump",
            "syn-20260901T030000Z-100.dump",
            "syn-20260901T030000Z-x.dump",
            "syn-2026090T030000Z.dump",
            "syn-20260901T030000.dump",
            "old-syn-20260901T030000Z.dump",
            # Named like a temp file, but not by this script.
            ".syn-operator.dump.partial.keep",
            ".syn-20260901T030000Z.dump.partial.keep",
            ".syn-20260901T030000Z.dump.partial.Ab12C",
            ".syn-20260901T030000Z.dump.partial.Ab12Cd7",
            ".syn-20260901T030000Z.dump.partial.Ab-2Cd",
            ".syn-20260901T030000Z.dump.manifest",
            "notes.txt",
            _LEDGER,
        ],
    )
    @pytest.mark.parametrize("tracked", [False, True], ids=["untracked", "in-ledger"])
    def test_never_deletes_a_name_it_does_not_generate_however_old(self, tmp_path, name, tracked):
        # Even a ledger line naming it (a hand-edited ledger) is not enough.
        foreign = self._make(tmp_path, name, 365 * _DAY, tracked=tracked)
        result = _run("prune", str(tmp_path), "1")
        assert result.returncode == 0, result.stderr
        assert foreign.exists(), f"prune deleted {name}, which it never created"
        assert name not in result.stdout

    @pytest.mark.parametrize(
        "name",
        [
            "syn-20260901T030000Z.dump",
            "syn-20260901T030000Z-3.dump",
            "syn-20260901T030000Z.dump.manifest",
            ".syn-20260901T030000Z.dump.partial.Ab12Cd",
        ],
    )
    def test_never_deletes_a_generated_name_it_did_not_create(self, tmp_path, name):
        """An operator's file in the generated shape, never recorded in the ledger."""
        self._make(tmp_path, "syn-20261008T030000Z.dump", 0)  # a ledger exists
        foreign = self._make(tmp_path, name, 365 * _DAY, tracked=False)

        assert _run("prune", str(tmp_path), "1").returncode == 0
        assert foreign.exists(), f"prune deleted {name}, which it never created"

    def test_never_deletes_a_file_put_in_place_of_one_it_created(self, tmp_path):
        ours = self._make(tmp_path, "syn-20260901T030000Z.dump", 365 * _DAY)
        replacement = tmp_path / "operator-copy"
        replacement.write_text("operator data")
        replacement.replace(ours)  # same name, different inode
        _age(ours, 365 * _DAY)

        assert _run("prune", str(tmp_path), "1").returncode == 0
        assert ours.read_text() == "operator data"

    def test_a_published_name_recorded_without_its_checksum_is_kept(self, tmp_path):
        ours = self._make(tmp_path, "syn-20260901T030000Z.dump", 365 * _DAY, tracked=False)
        (tmp_path / _LEDGER).write_text(f"{ours.stat().st_ino} - {ours.name}\n")

        assert _run("prune", str(tmp_path), "1").returncode == 0
        assert ours.exists()

    def test_never_deletes_content_written_over_one_it_created(self, tmp_path):
        """Same name, same inode (written in place, or a reused inode): other bytes."""
        ours = self._make(tmp_path, "syn-20260901T030000Z.dump", 365 * _DAY)
        ours.write_text("operator data")
        _age(ours, 365 * _DAY)

        assert _run("prune", str(tmp_path), "1").returncode == 0
        assert ours.read_text() == "operator data"

    def test_a_file_swapped_in_after_the_checks_is_put_back_not_deleted(self, tmp_path):
        """The check-then-delete race: prune deletes only what it renamed and re-checked."""
        ours = self._make(tmp_path, "syn-20260901T030000Z.dump", 365 * _DAY)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        swap = tmp_path / "swap"
        swap.write_text("operator data")
        real_find = shutil.which("find")
        # The age check is the last look before the rename: swap the file then.
        _stub(
            bin_dir,
            "find",
            f'[ "$1" = "{ours}" ] && [ -f "{swap}" ] && mv -f "{swap}" "{ours}"\n'
            f'exec {real_find} "$@"',
        )
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        _age(swap, 365 * _DAY)

        result = _run("prune", str(tmp_path), "1", env=env)

        assert result.returncode == 0, result.stderr
        assert ours.read_text() == "operator data"
        assert not list(tmp_path.glob(".syn-prune.*")), "left the operator file under a temp name"

    def test_without_a_ledger_nothing_is_pruned(self, tmp_path):
        old = self._make(tmp_path, "syn-20260901T030000Z.dump", 365 * _DAY, tracked=False)
        result = _run("prune", str(tmp_path), "1")
        assert result.returncode == 0, result.stderr
        assert old.exists()

    def test_never_follows_a_symlink_named_like_a_backup(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        target = self._make(elsewhere, "precious.dump", 365 * _DAY, tracked=False)
        backups = tmp_path / "backups"
        backups.mkdir()
        link = backups / "syn-20260901T030000Z.dump"
        link.symlink_to(target)
        _age(link, 365 * _DAY)
        # A forged ledger line naming the link with its own inode, and one
        # with its target's: neither may delete the link or what it points at.
        digest = hashlib.sha256(b"x").hexdigest()
        (backups / _LEDGER).write_text(
            f"{os.lstat(link).st_ino} {digest} {link.name}\n"
            f"{target.stat().st_ino} {digest} {link.name}\n"
        )

        assert _run("prune", str(backups), "1").returncode == 0
        assert target.exists()
        assert link.is_symlink()

    def test_prunes_what_backup_created(self, tmp_path, fake_pg):
        """The ledger handoff end to end: backup records, prune honours it."""
        out = tmp_path / "backups"
        out.mkdir()
        assert _run("backup", str(out), env=fake_pg(_LISTING_WITH_DATA)).returncode == 0
        created = sorted(p for p in out.iterdir() if p.name != _LEDGER)
        assert len(created) == 2
        for path in created:
            _age(path, 8 * _DAY)

        result = _run("prune", str(out), "7")

        assert result.returncode == 0, result.stderr
        assert [p for p in created if p.exists()] == []

    @pytest.mark.parametrize("days", ["0", "-1", "seven", ""])
    def test_rejects_retention_that_is_not_a_positive_whole_number(self, tmp_path, days):
        kept = self._make(tmp_path, "syn-20260901T030000Z.dump", 30 * _DAY)
        result = _run("prune", str(tmp_path), days)
        assert result.returncode != 0
        assert kept.exists()


class TestRestoreGuards:
    """Refusals that happen before the database is touched at all."""

    @staticmethod
    def _env(tmp_path: Path, *, populated: bool = True, dump_ok: bool = True) -> dict[str, str]:
        """psql that logs every statement; pg_dump that succeeds or fails."""
        bin_dir = tmp_path / "pgbin"
        bin_dir.mkdir()
        log = tmp_path / "psql-log"
        _stub(
            bin_dir,
            "psql",
            f'sql=$(cat; printf "%s\\n" "$@")\nprintf "%s\\n" "$sql" >> "{log}"\n'
            'case "$sql" in\n'
            "  *pg_database*) echo 1 ;;\n"
            f"  *information_schema*) {'echo public.events' if populated else ':'} ;;\n"
            "esac",
        )
        _stub(bin_dir, "pg_dump", "exit 0" if dump_ok else "echo 'pg_dump: boom' >&2; exit 1")
        _stub(bin_dir, "pg_restore", "exit 64")
        return {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "PGDATABASE": "syn",
            "SYN_BACKUP_DIR": str(tmp_path),
        }

    @staticmethod
    def _backup(tmp_path: Path, *, manifest: str | None = None) -> Path:
        dump = tmp_path / "syn-20261008T030000Z.dump"
        dump.write_bytes(b"archive bytes")
        if manifest is None:
            digest = hashlib.sha256(dump.read_bytes()).hexdigest()
            manifest = (
                f"syn-db-backup manifest 1\nsha256 {digest}\nrows 3 public.events\ntables 1\n"
            )
        (tmp_path / f"{dump.name}.manifest").write_text(manifest)
        return dump

    @staticmethod
    def _changed(tmp_path: Path) -> list[str]:
        log = tmp_path / "psql-log"
        text = log.read_text().lower() if log.exists() else ""
        return [w for w in ("create database", "alter database", "drop database") if w in text]

    def test_refuses_an_archive_that_does_not_match_its_checksum(self, tmp_path):
        env = self._env(tmp_path)
        dump = self._backup(tmp_path)
        # Cut short after the manifest was written.
        dump.write_bytes(dump.read_bytes()[:5])

        result = _run("restore", str(dump), "--force", env=env)

        assert result.returncode != 0
        assert "does not match its manifest" in result.stderr
        assert not (tmp_path / "psql-log").exists(), "connected before checking the archive"

    def test_refuses_an_archive_without_a_manifest(self, tmp_path):
        env = self._env(tmp_path)
        dump = self._backup(tmp_path)
        (tmp_path / f"{dump.name}.manifest").unlink()

        result = _run("restore", str(dump), "--force", env=env)

        assert result.returncode != 0
        assert "no manifest" in result.stderr
        assert not (tmp_path / "psql-log").exists()

    @pytest.mark.parametrize(
        "manifest",
        [
            "sha256 {d}\nrows 3 public.events\ntables 1\n",
            "syn-db-backup manifest 1\nrows 3 public.events\ntables 1\n",
            "syn-db-backup manifest 1\nsha256 {d}\nrows 3 public.events\n",
            "syn-db-backup manifest 1\nsha256 {d}\nrows 3 public.events\ntables 2\n",
            "syn-db-backup manifest 1\nsha256 {d}\ntables 0\n",
        ],
    )
    def test_refuses_an_incomplete_manifest(self, tmp_path, manifest):
        env = self._env(tmp_path)
        dump = self._backup(tmp_path)
        digest = hashlib.sha256(dump.read_bytes()).hexdigest()
        (tmp_path / f"{dump.name}.manifest").write_text(manifest.format(d=digest))

        result = _run("restore", str(dump), "--force", env=env)

        assert result.returncode != 0
        assert not (tmp_path / "psql-log").exists()

    def test_force_restores_nothing_when_the_backup_first_fails(self, tmp_path):
        env = self._env(tmp_path, dump_ok=False)
        dump = self._backup(tmp_path)

        result = _run("restore", str(dump), "--force", env=env)

        assert result.returncode != 0
        assert "could not back up 'syn' first" in result.stderr
        assert self._changed(tmp_path) == [], "touched a database after the backup failed"

    def test_without_force_a_populated_database_is_refused_unchanged(self, tmp_path):
        env = self._env(tmp_path)
        dump = self._backup(tmp_path)

        result = _run("restore", str(dump), env=env)

        assert result.returncode == 3
        assert "public.events" in result.stderr
        assert self._changed(tmp_path) == []


class TestCronMatch:
    @pytest.mark.parametrize(
        ("expr", "now", "matches"),
        [
            ("0 3 * * *", "0 3 08 10 4", True),
            ("0 3 * * *", "1 3 08 10 4", False),
            ("0 3 * * *", "0 4 08 10 4", False),
            ("*/15 * * * *", "45 7 1 1 1", True),
            ("*/15 * * * *", "44 7 1 1 1", False),
            ("5/10 * * * *", "25 0 1 1 1", True),
            ("0 2,14 * * *", "0 14 1 1 1", True),
            ("0 9-17 * * 1-5", "0 12 6 10 2", True),
            ("0 9-17 * * 1-5", "0 12 4 10 0", False),
            # 7 is Sunday as well as 0.
            ("0 0 * * 7", "0 0 4 10 0", True),
            # Both day fields restricted: either one matches (cron semantics).
            ("0 0 1 * 0", "0 0 4 10 0", True),
            ("0 0 1 * 0", "0 0 1 10 3", True),
            ("0 0 1 * 0", "0 0 2 10 3", False),
        ],
    )
    def test_standard_five_field_semantics(self, expr, now, matches):
        assert _run("cron-match", expr, now).returncode == (0 if matches else 1)

    @pytest.mark.parametrize(
        "expr", ["0 3 * * MON", "@daily", "0 3 * *", "60 3 * * *", "0 24 * * *", "*/0 * * * *"]
    )
    def test_rejects_what_it_cannot_honour(self, expr):
        result = _run("cron-match", expr, "0 3 1 1 1")
        assert result.returncode == 2
        assert "invalid cron expression" in result.stderr

    @pytest.mark.parametrize(
        "expr", ["0,60 3 * * *", "0 0 * * 0,MON", "0 0 31-1 * *", "0 5-3 * * *"]
    )
    @pytest.mark.parametrize("now", ["0 3 1 1 1", "0 0 1 1 0", "17 9 15 6 3"])
    def test_invalid_anywhere_is_invalid_at_any_time(self, expr, now):
        # A valid first list element, or a time that happens to match it, must
        # not hide an invalid tail or a range that can never match.
        result = _run("cron-match", expr, now)
        assert result.returncode == 2, (expr, now, result.stderr)

    @pytest.mark.parametrize("expr", ["0,60 3 * * *", "0 0 31-1 * *"])
    def test_schedule_refuses_to_start_on_an_invalid_tail_or_range(self, tmp_path, expr):
        result = subprocess.run(
            ["sh", str(_SCRIPT), "schedule", str(tmp_path), expr, "7"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode != 0
        assert "BACKUP_SCHEDULE" in result.stderr

    def test_schedule_refuses_to_start_on_an_invalid_expression(self, tmp_path):
        result = subprocess.run(
            ["sh", str(_SCRIPT), "schedule", str(tmp_path), "0 3 * * MON", "7"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode != 0
        assert "BACKUP_SCHEDULE" in result.stderr


class TestComposeService:
    """The service is the only consumer of the three BACKUP_* settings."""

    @staticmethod
    def _services(path: Path) -> dict:
        return yaml.safe_load(path.read_text())["services"]

    def test_client_tools_match_the_database_image(self):
        backup = self._services(_SELFHOST)["db-backup"]
        database = self._services(_BASE)["timescaledb"]
        assert backup["image"] == database["image"], (
            "pg_dump/pg_restore must come from the same image as the server"
        )

    def test_backup_settings_reach_the_scheduler_with_settings_defaults(self):
        from syn_shared.settings.infra import InfraSettings

        fields = InfraSettings.model_fields
        backup = self._services(_SELFHOST)["db-backup"]

        assert backup["command"] == [
            "schedule",
            "/backups",
            f"${{BACKUP_SCHEDULE:-{fields['backup_schedule'].default}}}",
            f"${{BACKUP_RETENTION_DAYS:-{fields['backup_retention_days'].default}}}",
        ]
        assert f"${{BACKUP_DIR:-{fields['backup_dir'].default}}}:/backups" in backup["volumes"]

    def test_scheduler_reads_its_identity_from_the_database_container(self):
        services = self._services(_SELFHOST)
        backup, database = services["db-backup"], services["timescaledb"]
        env = backup["environment"]
        assert "PGUSER" not in env and "PGDATABASE" not in env, (
            "interpolated from infra/.env, not from the running database"
        )
        identity = Path(env["SYN_DB_IDENTITY_FILE"])
        assert f"db_identity:{identity.parent}" in database["volumes"]
        assert f"db_identity:{identity.parent}:ro" in backup["volumes"]
        assert str(identity) in database["healthcheck"]["test"][1]

    def test_script_mounted_is_the_one_tested_here(self):
        backup = self._services(_SELFHOST)["db-backup"]
        source = backup["volumes"][0].split(":")[0]
        assert (_SELFHOST.parent / source).resolve() == _SCRIPT
        assert backup["entrypoint"] == ["sh", "/usr/local/bin/syn-db-backup"]


class TestJustRecipes:
    @staticmethod
    def _recipe(name: str) -> str:
        text = (_ROOT / "justfile").read_text()
        match = re.search(rf"^{name}\b.*?:\n((?:    .*\n|\n)+)", text, re.MULTILINE)
        assert match, f"no {name} recipe"
        return match.group(1)

    def test_manual_backup_runs_the_scheduled_command(self):
        assert "db-backup backup /backups" in self._recipe("selfhost-backup")

    def test_restore_stops_the_writers_the_upgrade_runbook_stops(self):
        runbook = (_ROOT / "docs" / "deployment" / "timescaledb-2.29-upgrade.md").read_text()
        stopped = re.search(r'docker compose -f "\$CF" stop ([a-z -]+)\n', runbook)
        assert stopped
        writers = re.search(r'writers="([a-z -]+)"', self._recipe("selfhost-restore"))
        assert writers
        assert set(writers.group(1).split()) == set(stopped.group(1).split())

    @pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
    @pytest.mark.parametrize(
        "name", ["literal-$(touch {sentinel}).dump", 'a "quoted" `touch {sentinel}` b.dump']
    )
    def test_restore_file_name_is_data_not_shell(self, tmp_path, name):
        sentinel = tmp_path / "substituted"
        backup = tmp_path / name.format(sentinel=sentinel)
        result = subprocess.run(
            ["just", "selfhost-restore", str(backup)],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode != 0
        assert f"No such backup: {backup}" in result.stdout
        assert not sentinel.exists(), "the file name was run as a command"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
class TestDatabaseIdentity:
    """Both recipes connect as the running container says, not as the env file says."""

    @staticmethod
    def _docker(tmp_path: Path) -> tuple[dict[str, str], Path]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "docker-calls"
        _stub(
            bin_dir,
            "docker",
            f'printf "%s\\n" "$*" >> "{calls}"\n'
            'case "$*" in\n'
            '  *"printenv POSTGRES_USER"*) echo container_user ;;\n'
            '  *"printenv POSTGRES_DB"*) echo container_db ;;\n'
            "esac",
        )
        # What a stale shell / infra/.env would say.
        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "POSTGRES_USER": "file_user",
            "POSTGRES_DB": "file_db",
            "PGUSER": "file_user",
            "PGDATABASE": "file_db",
        }
        return env, calls

    def test_backup_uses_the_container_identity(self, tmp_path):
        env, calls = self._docker(tmp_path)
        result = subprocess.run(
            ["just", "selfhost-backup"],
            cwd=_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        run = next(c for c in calls.read_text().splitlines() if " run " in c)
        assert "-e PGUSER=container_user -e PGDATABASE=container_db db-backup backup" in run
        assert "file_" not in run

    def test_restore_uses_the_container_identity(self, tmp_path):
        env, calls = self._docker(tmp_path)
        backup = tmp_path / "syn-20261008T030000Z.dump"
        backup.write_text("x")
        # The in-flight execution check needs a live API; stand it in.
        _stub(tmp_path / "bin", "uv", "exit 0")
        result = subprocess.run(
            ["just", "selfhost-restore", str(backup)],
            cwd=_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        run = next(c for c in calls.read_text().splitlines() if " run " in c)
        assert "-e PGUSER=container_user -e PGDATABASE=container_db" in run
        assert "db-backup restore /restore/syn-20261008T030000Z.dump" in run
        assert "file_" not in run


class TestScheduledIdentity:
    """The schedule connects as the running database container says."""

    def test_schedule_uses_the_identity_the_database_container_wrote(self, tmp_path, fake_pg):
        """The handoff end to end: timescaledb's healthcheck writes, the schedule reads."""
        env = fake_pg(_LISTING_WITH_DATA)
        bin_dir = Path(env["PATH"].split(os.pathsep)[0])
        connected = tmp_path / "connected-as"
        _stub(
            bin_dir,
            "pg_dump",
            f'echo "$PGUSER $PGDATABASE" > "{connected}"\n'
            'for a in "$@"; do case $a in --file=*) echo archive > "${a#--file=}";; esac; done',
        )
        # Ends the schedule loop after its first pass.
        _stub(bin_dir, "sleep", "exit 99")
        _stub(bin_dir, "pg_isready", "exit 0")

        # The healthcheck as the database container runs it: Compose has
        # interpolated ${...} from infra/.env and unescaped $$, and the
        # container's own environment is the only other source.
        handoff = tmp_path / "identity"
        handoff.mkdir()
        services = yaml.safe_load(_SELFHOST.read_text())["services"]
        stale = {"POSTGRES_USER": "file_user", "POSTGRES_DB": "file_db"}
        check = re.sub(
            r"\$\$|\$\{(\w+)(?::-[^}]*)?\}",
            lambda m: "$" if m.group(0) == "$$" else stale[m.group(1)],
            services["timescaledb"]["healthcheck"]["test"][1],
        ).replace("/syn-db-identity", str(handoff))
        database_env = {**env, "POSTGRES_USER": "container_user", "POSTGRES_DB": "container_db"}
        assert subprocess.run(["sh", "-c", check], env=database_env, check=False).returncode == 0

        # What a stale shell / infra/.env would say, in the scheduler's env.
        scheduler_env = {
            **env,
            "PGUSER": "file_user",
            "PGDATABASE": "file_db",
            "SYN_DB_IDENTITY_FILE": str(handoff / "identity"),
        }
        out = tmp_path / "backups"
        out.mkdir()
        result = subprocess.run(
            ["sh", str(_SCRIPT), "schedule", str(out), "* * * * *", "7"],
            env=scheduler_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert "backup ok" in result.stdout, result.stderr
        assert connected.read_text().split() == ["container_user", "container_db"]

    def test_schedule_without_an_identity_fails_the_backup_not_the_schedule(
        self, tmp_path, fake_pg
    ):
        env = fake_pg(_LISTING_WITH_DATA)
        _stub(Path(env["PATH"].split(os.pathsep)[0]), "sleep", "exit 99")
        out = tmp_path / "backups"
        out.mkdir()
        result = subprocess.run(
            ["sh", str(_SCRIPT), "schedule", str(out), "* * * * *", "7"],
            env={**env, "PGUSER": "file_user", "SYN_DB_IDENTITY_FILE": str(tmp_path / "none")},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert "no database identity" in result.stderr
        assert "scheduled backup FAILED" in result.stderr
        assert not list(out.glob("syn-*.dump")), "dumped as the env file's identity"
