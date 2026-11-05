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


def _epochs(new: str, old: str) -> str:
    return f"""    case "$*" in
        *"docker run"*) echo '{new}' ;;
        *"docker exec syn137-executor"*) echo '{old}' ;;
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

    def _room(self, tmp: Path, running: int, queued: int, limit: int) -> int:
        body = (
            f'api() {{ echo \'{{"budget": {{"running": {running}, '
            f'\\"queued\\": {queued}, \\"limit\\": {limit}}}}}\' > "$2"; }}\n'.replace('\\"', '"')
            + _between("executor_has_room() {", 'PROBE_LINE=""\n')
            + "executor_has_room"
        )
        return _run(tmp, body, "    :").returncode

    def test_a_free_slot_has_room(self, tmp_path: Path) -> None:
        assert self._room(tmp_path, 3, 0, 10) == 0

    @pytest.mark.parametrize(("running", "queued"), [(10, 0), (8, 2)])
    def test_a_full_budget_has_none(self, tmp_path: Path, running: int, queued: int) -> None:
        assert self._room(tmp_path, running, queued, 10) == 1
