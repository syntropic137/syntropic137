"""The self-host database backup: naming, verification, retention, schedule.

``docker/db-backup/syn-db-backup.sh`` is the one implementation behind
``just selfhost-backup``, ``just selfhost-restore`` and the scheduled
``db-backup`` service. These tests run the real script with stand-in
``pg_dump`` / ``pg_restore`` on PATH, so they need no database. The
round trip through a real TimescaleDB, hypertables included, is
``test_db_backup_integration.py``.
"""

from __future__ import annotations

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


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def fake_pg(tmp_path: Path):
    """PATH with pg_dump writing a file and pg_restore listing LISTING."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "pg_dump",
        'for a in "$@"; do case $a in'
        ' --file=*) echo "${DUMP_PAYLOAD:-archive}" > "${a#--file=}";; esac; done',
    )

    def configure(listing: str | None) -> dict[str, str]:
        if listing is None:
            _stub(
                bin_dir,
                "pg_restore",
                'echo "pg_restore: error: input file is too short" >&2; exit 1',
            )
        else:
            (tmp_path / "listing").write_text(listing)
            _stub(bin_dir, "pg_restore", f'cat "{tmp_path / "listing"}"')
        return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    return configure


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(_SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )


class TestBackup:
    def test_verified_dump_is_kept_under_a_timestamped_name(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        result = _run("backup", str(out), env=fake_pg(_LISTING_WITH_DATA))

        assert result.returncode == 0, result.stderr
        files = sorted(p.name for p in out.iterdir())
        assert len(files) == 1
        assert re.fullmatch(r"syn-\d{8}T\d{6}Z\.dump", files[0]), files
        assert f"backup ok: {out}/{files[0]}" in result.stdout
        assert "2 tables" in result.stdout
        # A dump holds every event: never world- or group-readable.
        assert stat.S_IMODE((out / files[0]).stat().st_mode) == 0o600

    def test_archive_without_table_data_is_not_kept(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        result = _run("backup", str(out), env=fake_pg(_LISTING_WITHOUT_DATA))

        assert result.returncode != 0
        assert "no table data" in result.stderr
        assert list(out.iterdir()) == [], "a failed backup must leave nothing behind"

    def test_unreadable_archive_is_not_kept(self, tmp_path, fake_pg):
        out = tmp_path / "backups"
        out.mkdir()
        result = _run("backup", str(out), env=fake_pg(None))

        assert result.returncode != 0
        assert "cannot read" in result.stderr
        assert list(out.iterdir()) == []

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
        assert sorted(p.name for p in out.iterdir()) == [
            "syn-20261008T030000Z-1.dump",
            "syn-20261008T030000Z.dump",
        ]

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
        payloads = sorted(p.read_text() for p in out.iterdir())
        assert payloads == [f"archive-{i}\n" for i in range(4)]


class TestPrune:
    def _make(self, directory: Path, name: str, age_seconds: float) -> Path:
        path = directory / name
        path.write_text("x")
        then = time.time() - age_seconds
        os.utime(path, (then, then))
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

    def test_abandoned_partial_dumps_are_cleared_after_a_day(self, tmp_path):
        stale = self._make(tmp_path, ".syn-20260901T030000Z.dump.partial", 2 * _DAY)
        live = self._make(tmp_path, ".syn-20261008T030000Z.dump.partial", 60)

        assert _run("prune", str(tmp_path), "7").returncode == 0
        assert not stale.exists()
        assert live.exists(), "a dump in progress must not be deleted under it"

    @pytest.mark.parametrize("days", ["0", "-1", "seven", ""])
    def test_rejects_retention_that_is_not_a_positive_whole_number(self, tmp_path, days):
        kept = self._make(tmp_path, "syn-20260901T030000Z.dump", 30 * _DAY)
        result = _run("prune", str(tmp_path), days)
        assert result.returncode != 0
        assert kept.exists()


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
