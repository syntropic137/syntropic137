"""`--service api` swaps the API with no drain; `all` moves an executor too (#1310, 1.6).

With the Run Queue on, runs live in the executor, so recreating the API needs
neither the gate nor the drain. With it off, every run lives inside the API and
this path would kill them all, so it refuses. `all` keeps its drain and gains the
executor: left behind, it would stay on the old build for ever.

Dry runs reuse the whole-script harness of the gateway-only tests. The checks
that only run for real are run as written, sliced from the script.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_1310_pit_stop_gateway_only import _SCRIPT, _dry_run, _lines

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).parent / "fixtures" / "pit_stop"
_SPLIT = {"PIT_RUN_QUEUE": "true", "PIT_EXECUTOR_ID": "abc123"}


def _with_executor(tmp: Path) -> str:
    """The tag fixture plus an executor on the syn-api image, as a release compose has."""
    compose = tmp / "compose-executor.yaml"
    base = (_FIXTURES / "compose-tag.yaml").read_text()
    api_image = next(ln for ln in base.splitlines() if "syn-api:" in ln).strip()
    head, services, rest = base.partition("services:\n")
    compose.write_text(
        f'{head}{services}  executor:\n    profiles: ["run-queue"]\n    {api_image}\n{rest}'
    )
    return str(compose)


class TestRefusesUnlessTheRunsAreElsewhere:
    @pytest.mark.parametrize("queue", ["", "false", "0"])
    def test_the_run_queue_off_is_refused_before_any_build(
        self, tmp_path: Path, queue: str
    ) -> None:
        out, err, _ = _dry_run(
            tmp_path,
            "--service",
            "api",
            rc=1,
            extra_env={**_SPLIT, "PIT_RUN_QUEUE": queue},
        )
        assert "the Run Queue is off" in err
        assert "buildx" not in out

    @pytest.mark.parametrize("queue", ["true", "True", "1"])
    def test_every_spelling_settings_reads_as_on_passes(self, tmp_path: Path, queue: str) -> None:
        out, _, _ = _dry_run(
            tmp_path, "--service", "api", extra_env={**_SPLIT, "PIT_RUN_QUEUE": queue}
        )
        assert "DRY RUN DONE" in out

    @pytest.mark.parametrize("role", ["all", "executor", ""])
    def test_an_api_that_may_hold_runs_is_refused(self, tmp_path: Path, role: str) -> None:
        """Role `all` claims queued runs in the API process, flag on or not."""
        _, err, _ = _dry_run(
            tmp_path, "--service", "api", rc=1, extra_env={**_SPLIT, "PIT_API_ROLE": role}
        )
        assert "may hold runs of its own" in err

    def test_no_executor_is_refused(self, tmp_path: Path) -> None:
        _, err, _ = _dry_run(
            tmp_path, "--service", "api", rc=1, extra_env={"PIT_RUN_QUEUE": "true"}
        )
        assert "no syn137-executor" in err

    def test_a_stopped_executor_is_refused(self, tmp_path: Path) -> None:
        _, err, _ = _dry_run(
            tmp_path,
            "--service",
            "api",
            rc=1,
            extra_env={**_SPLIT, "PIT_EXECUTOR_RUNNING": "false"},
        )
        assert "syn137-executor is not running" in err


class TestTheApiAlone:
    def test_builds_and_ships_only_syn_api(self, tmp_path: Path) -> None:
        out, _, _ = _dry_run(tmp_path, "--service", "api", extra_env=_SPLIT)
        (build,) = _lines(out, "buildx build")
        assert "syn-api" in build
        (ship,) = _lines(out, "(dry-run) docker save")
        assert "syn-gateway" not in ship

    def test_never_touches_admission_or_waits_for_a_drain(self, tmp_path: Path) -> None:
        out, _, log = _dry_run(tmp_path, "--service", "api", extra_env=_SPLIT)
        assert "gate:" not in out
        assert "drain:" not in out
        assert "/maintenance" not in (log / "curl").read_text()

    def test_recreates_the_api_without_its_dependencies(self, tmp_path: Path) -> None:
        out, _, _ = _dry_run(tmp_path, "--service", "api", extra_env=_SPLIT)
        (up,) = _lines(out, "docker compose")
        assert up.rstrip().endswith("up -d --no-deps api")

    def test_still_proves_a_run_can_start(self, tmp_path: Path) -> None:
        """Admission is API code, so #1641's hazard applies here: unlike the
        gateway, this path keeps the probe and its precheck."""
        out, _, log = _dry_run(tmp_path, "--service", "api", extra_env=_SPLIT)
        assert "/workflows" in (log / "curl").read_text()
        assert "(dry-run) POST /workflows/" in out


class TestAllMovesTheExecutor:
    def test_a_host_with_an_executor_recreates_it_with_the_api(self, tmp_path: Path) -> None:
        compose = _with_executor(tmp_path)
        out, _, _ = _dry_run(tmp_path, compose=compose, extra_env=_SPLIT)
        (up,) = _lines(out, "docker compose")
        assert up.rstrip().endswith("up -d api gateway executor")
        assert "repoint all three pins" in out
        assert "drain:" in out, "`all` keeps its drain: the executor's runs would die otherwise"

    def test_a_host_without_one_never_names_it(self, tmp_path: Path) -> None:
        """Naming a profiled service to compose starts it."""
        compose = _with_executor(tmp_path)
        out, _, _ = _dry_run(tmp_path, compose=compose)
        (up,) = _lines(out, "docker compose")
        assert up.rstrip().endswith("up -d api gateway")


def _between(start: str, end: str) -> str:
    text = _SCRIPT.read_text()
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def _run(tmp: Path, body: str, remote: str) -> subprocess.CompletedProcess[str]:
    prelude = f"""
set -euo pipefail
SERVICE=api; DRY=0; TAG=v9; HOST=fake; TMP={tmp}; EXECUTOR_ID=abc123
COMPOSE_DIR=/c; STAGED=staged.yaml
step() {{ :; }}
die() {{ printf 'ABORTED: %s\\n' "$*" >&2; exit 1; }}
remote() {{
{remote}
}}
"""
    return subprocess.run(
        ["bash", "-c", prelude + body],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _epochs(new: str, old: str, role: str = "api", queue: str = "true") -> str:
    resolved = '{"services": {"api": {"environment": {'
    resolved += f'"SYN_EXECUTION_PROCESS_ROLE": "{role}", '
    resolved += f'"SYN_EXECUTION_RUN_QUEUE_ENABLED": "{queue}"}}}}}}}}'
    return f"""    case "$*" in
        *"docker run"*) echo '{new}' ;;
        *"docker exec syn137-executor"*) echo '{old}' ;;
        *"config --format json"*) echo '{resolved}' ;;
    esac"""


class TestTheEventEpochGuard:
    """A newer API would admit runs this executor may not claim: nothing fails,
    they queue for ever (ADR-072 D9)."""

    def _guard(self) -> str:
        return _between("epoch_of() {", "# Gated and drained, nothing recreated yet")

    def test_the_same_epoch_passes(self, tmp_path: Path) -> None:
        proc = _run(tmp_path, self._guard(), _epochs("9", "9"))
        assert proc.returncode == 0, proc.stderr
        assert "executor=9 new image=9" in proc.stdout

    @pytest.mark.parametrize(("new", "old"), [("10", "9"), ("9", "10")])
    def test_a_different_epoch_is_refused(self, tmp_path: Path, new: str, old: str) -> None:
        proc = _run(tmp_path, self._guard(), _epochs(new, old))
        assert proc.returncode == 1
        assert "use --service all" in proc.stderr

    @pytest.mark.parametrize(("role", "queue"), [("api", "false"), ("api", ""), ("all", "true")])
    def test_a_new_api_that_would_start_unsplit_is_refused(
        self, tmp_path: Path, role: str, queue: str
    ) -> None:
        """.env may have moved since the running container started: flag off,
        and the new API's startup reconcile reaps the executor's workspaces."""
        proc = _run(tmp_path, self._guard(), _epochs("9", "9", role, queue))
        assert proc.returncode == 1
        assert "reaps the executor's runs" in proc.stderr

    def test_the_resolved_config_never_reaches_the_output(self, tmp_path: Path) -> None:
        remote = _epochs("9", "9").replace(
            '"SYN_EXECUTION_PROCESS_ROLE"', '"A_SECRET": "hunter2", "SYN_EXECUTION_PROCESS_ROLE"'
        )
        proc = _run(tmp_path, self._guard(), remote)
        assert proc.returncode == 0, proc.stderr
        assert "hunter2" not in proc.stdout + proc.stderr

    def test_an_image_that_reports_nothing_is_refused(self, tmp_path: Path) -> None:
        proc = _run(tmp_path, self._guard(), _epochs("", ""))
        assert proc.returncode == 1
        assert "reported no event epoch" in proc.stderr


class TestTheExecutorIsReadBack:
    def _check(self) -> str:
        return _between(
            '    if [ "${SERVICE:-all}" = api ]; then\n        [ "$(remote "docker inspect',
            "    wait_for_api_ready ||",
        )

    def test_the_same_container_passes(self, tmp_path: Path) -> None:
        proc = _run(tmp_path, self._check(), "    echo abc123")
        assert proc.returncode == 0, proc.stderr

    def test_a_recreated_executor_fails_verify(self, tmp_path: Path) -> None:
        proc = _run(tmp_path, self._check(), "    echo def456")
        assert proc.returncode == 1
        assert "was recreated by an API-only swap" in proc.stderr


class TestAProbeNeedsARoom:
    """No drain means every slot may be taken: a probe would queue past its
    deadline and report a healthy swap as broken."""

    def _room(self, tmp: Path, block: str) -> int:
        (tmp / "health.json").write_text('{"execution_budget": ' + block + "}")
        body = (
            f'api() {{ cp {tmp}/health.json "$2"; }}\n'
            + _between("executor_has_room() {", 'PROBE_LINE=""\n')
            + "executor_has_room"
        )
        return _run(tmp, body, "    :").returncode

    def test_a_free_slot_has_room(self, tmp_path: Path) -> None:
        assert self._room(tmp_path, '{"budget": 10, "running": 3, "queued": 0}') == 0

    @pytest.mark.parametrize(("running", "queued"), [(10, 0), (8, 2)])
    def test_a_full_budget_has_none(self, tmp_path: Path, running: int, queued: int) -> None:
        block = f'{{"budget": 10, "running": {running}, "queued": {queued}}}'
        assert self._room(tmp_path, block) == 1

    def test_an_unreadable_budget_has_none(self, tmp_path: Path) -> None:
        assert self._room(tmp_path, "null") == 1


class TestRecoveryWithAnExecutor:
    def _text(self, tmp: Path, marker: str, also: str) -> str:
        body = f"ALSO_PINNED={also!r}; COMPOSE=c.yaml; API=http://a; BAK=b; SWAP_ARGS=x\n"
        body += _between(
            marker, "fi\n# From here" if "RECOVERY=" in marker else '    RECOVERY="$TAG'
        )
        return _run(tmp, body + '\necho "${RECOVERY:-$rollback}"', "    :").stdout

    def test_a_partial_swap_finishes_the_executor_before_admission(self, tmp_path: Path) -> None:
        text = self._text(
            tmp_path, 'RECOVERY="RECOVERY: admission is still PAUSED. Once', "executor"
        )
        assert "up -d gateway executor" in text
        assert "must name v9" in text

    def test_no_executor_keeps_the_recovery_as_it_was(self, tmp_path: Path) -> None:
        text = self._text(tmp_path, 'RECOVERY="RECOVERY: admission is still PAUSED. Once', "")
        assert "up -d gateway'" in text
        assert "syn137-executor" not in text

    def test_the_rollback_after_the_ungate_never_recreates_the_executor(
        self, tmp_path: Path
    ) -> None:
        text = self._text(tmp_path, 'rollback="ssh $HOST', "executor")
        assert "do NOT recreate syn137-executor" in text
        assert "up -d" not in text
