"""Host side of ``just selfhost-backup`` / ``just selfhost-restore``.

``infra/scripts/selfhost_backup.py`` runs here against a stand-in ``docker``
on PATH that records every call, so no stack is needed.
"""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from infra.scripts.selfhost_backup import WRITERS, main

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = "docker compose -f docker/docker-compose.yaml -f docker/docker-compose.selfhost.yaml"


class FakeDocker:
    """A ``docker`` on PATH: logs argv, answers printenv, exits as told for run."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls_file = tmp_path / "docker-calls"
        self.bin_dir = tmp_path / "bin"
        self.bin_dir.mkdir()
        self._monkeypatch = monkeypatch
        self.configure()
        monkeypatch.setenv("PATH", f"{self.bin_dir}:{Path('/usr/bin')}:{Path('/bin')}")
        # What a stale shell / infra/.env would say.
        for name, value in {
            "POSTGRES_USER": "file_user",
            "POSTGRES_DB": "file_db",
            "PGUSER": "file_user",
            "PGDATABASE": "file_db",
        }.items():
            monkeypatch.setenv(name, value)

    def configure(self, *, run_exit: int = 0, running: bool = True, run_output: str = "") -> None:
        printenv = (
            '  *"printenv POSTGRES_USER"*) echo container_user ;;\n'
            '  *"printenv POSTGRES_DB"*) echo container_db ;;\n'
            if running
            else '  *printenv*) echo "service not running" >&2; exit 1 ;;\n'
        )
        path = self.bin_dir / "docker"
        path.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> "{self.calls_file}"\n'
            'case "$*" in\n'
            f"{printenv}"
            f"  *\" run \"*) printf '{run_output}'; exit {run_exit} ;;\n"
            "esac\n"
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    @property
    def calls(self) -> list[str]:
        if not self.calls_file.exists():
            return []
        return self.calls_file.read_text().splitlines()

    def run_call(self) -> str:
        return next(c for c in self.calls if " run " in c)


@pytest.fixture
def docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    return FakeDocker(tmp_path, monkeypatch)


class PredeployCheck:
    def __init__(self, rc: int = 0) -> None:
        self.rc = rc
        self.args: list[str] | None = None

    def __call__(self, args: Sequence[str]) -> int:
        self.args = list(args)
        return self.rc


def _backup_file(tmp_path: Path) -> Path:
    path = tmp_path / "syn-20261008T030000Z.dump"
    path.write_text("x")
    return path


class TestBackup:
    def test_runs_the_scheduled_command_as_the_container_identity(self, docker):
        assert main(["--compose", _COMPOSE, "backup"]) == 0
        run = docker.run_call()
        assert run.startswith(_COMPOSE.removeprefix("docker ") + " run --rm --no-TTY")
        assert (
            "-e PGUSER=container_user -e PGDATABASE=container_db db-backup backup /backups" in run
        )
        assert "file_" not in run

    def test_reports_host_paths(self, docker, monkeypatch, capsys):
        monkeypatch.setenv("BACKUP_DIR", "/srv/syn-backups")
        docker.configure(run_output="backup ok: /backups/syn-20261008T030000Z.dump\\n")
        assert main(["--compose", _COMPOSE, "backup"]) == 0
        assert "backup ok: /srv/syn-backups/syn-20261008T030000Z.dump" in capsys.readouterr().out

    def test_default_backup_dir_when_unset_or_empty(self, docker, monkeypatch, capsys):
        monkeypatch.setenv("BACKUP_DIR", "")
        docker.configure(run_output="/backups/a.dump\\n")
        assert main(["--compose", _COMPOSE, "backup"]) == 0
        assert "/var/backups/syn/a.dump" in capsys.readouterr().out

    def test_failure_exit_code_is_the_backups(self, docker):
        docker.configure(run_exit=5)
        assert main(["--compose", _COMPOSE, "backup"]) == 5

    def test_stopped_database_is_reported_and_nothing_runs(self, docker, capsys):
        docker.configure(running=False)
        assert main(["--compose", _COMPOSE, "backup"]) == 1
        assert "timescaledb is not running" in capsys.readouterr().out
        assert not any(" run " in c for c in docker.calls)


class TestRestore:
    def test_missing_file_is_refused_before_anything_runs(self, tmp_path, docker, capsys):
        check = PredeployCheck()
        missing = tmp_path / "nope.dump"
        assert main(["--compose", _COMPOSE, "restore", str(missing)], check) == 1
        assert f"No such backup: {missing}" in capsys.readouterr().out
        assert check.args is None
        assert docker.calls == []

    def test_in_flight_executions_stop_the_restore(self, tmp_path, docker):
        check = PredeployCheck(rc=1)
        file = _backup_file(tmp_path)
        assert main(["--compose", _COMPOSE, "restore", str(file)], check) == 1
        assert docker.calls == []

    def test_stops_writers_restores_and_starts_them(self, tmp_path, docker, capsys):
        check = PredeployCheck()
        file = _backup_file(tmp_path)
        assert main(["--compose", _COMPOSE, "restore", str(file), "--force"], check) == 0
        assert check.args == ["--force"]
        calls = docker.calls
        run = docker.run_call()
        stop = next(i for i, c in enumerate(calls) if c.endswith(f"stop {' '.join(WRITERS)}"))
        start = next(i for i, c in enumerate(calls) if c.endswith(f"start {' '.join(WRITERS)}"))
        assert stop < calls.index(run) < start
        assert "-e PGUSER=container_user -e PGDATABASE=container_db" in run
        assert f"-v {tmp_path.resolve()}:/restore:ro" in run
        assert run.endswith("db-backup restore /restore/syn-20261008T030000Z.dump --force")
        assert "file_" not in run
        assert "admission is PAUSED" in capsys.readouterr().out

    def test_refused_populated_database_starts_writers_again(self, tmp_path, docker, capsys):
        docker.configure(run_exit=3)
        file = _backup_file(tmp_path)
        assert main(["--compose", _COMPOSE, "restore", str(file)], PredeployCheck()) == 3
        assert any(c.endswith(f"start {' '.join(WRITERS)}") for c in docker.calls)
        assert "PAUSED" not in capsys.readouterr().out
        assert not docker.run_call().endswith("--force")

    def test_failed_restore_leaves_writers_stopped(self, tmp_path, docker, capsys):
        docker.configure(run_exit=1)
        file = _backup_file(tmp_path)
        assert main(["--compose", _COMPOSE, "restore", str(file)], PredeployCheck()) == 1
        assert not any(" start " in c for c in docker.calls)
        out = capsys.readouterr().out
        assert "Writers left STOPPED" in out
        assert f"start {' '.join(WRITERS)}" in out

    @pytest.mark.parametrize(
        "name", ["literal-$(touch {sentinel}).dump", 'a "quoted" `touch {sentinel}` b.dump']
    )
    def test_file_name_is_data_not_shell(self, tmp_path, docker, monkeypatch, name):
        # A relative sentinel, so the name is creatable; a substitution would
        # create it in the working directory.
        monkeypatch.chdir(tmp_path)
        sentinel = tmp_path / "substituted"
        file = tmp_path / name.format(sentinel="substituted")
        file.write_text("x")
        assert main(["--compose", _COMPOSE, "restore", str(file)], PredeployCheck()) == 0
        assert not sentinel.exists(), "the file name was run as a command"
        assert docker.run_call().endswith(f"/restore/{file.name}")


class TestWritersMatchTheRunbook:
    def test_restore_stops_the_writers_the_upgrade_runbook_stops(self):
        runbook = (_ROOT / "docs" / "deployment" / "timescaledb-2.29-upgrade.md").read_text()
        stopped = re.search(r'docker compose -f "\$CF" stop ([a-z -]+)\n', runbook)
        assert stopped
        assert set(WRITERS) == set(stopped.group(1).split())


class TestRecipesOnlyCallTheProgram:
    """The owner's rule: no logic in the justfile; it calls the tested program."""

    @staticmethod
    def _recipe(name: str) -> list[str]:
        text = (_ROOT / "justfile").read_text()
        match = re.search(rf"^{name}\b.*?:\n((?:    .*\n)+)", text, re.MULTILINE)
        assert match, f"no {name} recipe"
        return [line.strip() for line in match.group(1).splitlines()]

    @pytest.mark.parametrize(
        ("recipe", "call"),
        [
            ("selfhost-backup", "backup"),
            ("selfhost-restore", 'restore "$@"'),
        ],
    )
    def test_recipe_is_env_then_one_call(self, recipe, call):
        assert self._recipe(recipe) == [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "source infra/scripts/selfhost-env.sh",
            "exec uv run python infra/scripts/selfhost_backup.py"
            f' --compose "{{{{compose_selfhost}}}}" {call}',
        ]

    @pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
    def test_restore_file_name_reaches_the_program_as_data(self, tmp_path):
        sentinel = tmp_path / "substituted"
        missing = tmp_path / f"literal-$(touch {sentinel}).dump"
        result = subprocess.run(
            ["just", "selfhost-restore", str(missing)],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode != 0
        assert f"No such backup: {missing}" in result.stdout
        assert not sentinel.exists(), "the file name was run as a command"


class TestPublishedCompose:
    """The published install has no db-backup, so no handoff to it either."""

    def test_timescaledb_keeps_the_base_healthcheck_and_no_repo_mounts(self):
        published = yaml.safe_load(
            (_ROOT / "docker" / "docker-compose.syntropic137.yaml").read_text()
        )
        base = yaml.safe_load((_ROOT / "docker" / "docker-compose.yaml").read_text())
        database = published["services"]["timescaledb"]
        assert (
            database["healthcheck"]["test"]
            == base["services"]["timescaledb"]["healthcheck"]["test"]
        )
        assert not [v for v in database["volumes"] if "db_identity" in v or "db-backup" in v]
        assert "db_identity" not in published["volumes"]
        assert "db-backup" not in published["services"]
