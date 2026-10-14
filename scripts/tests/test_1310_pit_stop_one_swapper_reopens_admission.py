"""One swapper at a time, taken before anything ships, and what each exit does
to admission (#1310 1.6, with #1575 narrowed rather than reversed).

Before the swap, every exit after the gate RE-OPENS admission: nothing was
recreated, so a gate left shut is pure outage. From the first ``swap_up`` on,
every exit leaves admission PAUSED and prints RECOVERY: a build that has not
passed verify never takes traffic.

These run the script's own lines (the lock-and-trap block, the gate, and the
``SWAPPING=1`` that precedes the swap) with ``remote`` playing the host and
``maintenance`` recording every PUT, then end the run the ways a pit stop ends.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"
_START = "# ONE SWAPPER AT A TIME"
_CLAIM = 'if [ "$DRY" = 0 ]; then claim_the_swap; fi'
_GATE = 'maintenance true "pit stop $VERSION"'
_SWAP = "if ! swap_up; then"


def _lines() -> list[str]:
    return _SCRIPT.read_text().splitlines()


def _lock_block() -> str:
    """From the lock through the claim, verbatim."""
    lines = _lines()
    start = next(i for i, line in enumerate(lines) if line.startswith(_START))
    return "\n".join(lines[start : lines.index(_CLAIM) + 1])


def _gate() -> str:
    """The gate as written: the flag, then the PUT."""
    lines = _lines()
    gate = next(i for i, line in enumerate(lines) if line.startswith(_GATE))
    assert lines[gate - 1] == "GATED=1", "the flag must be armed on the line BEFORE the pause PUT"
    return "\n".join(lines[gate - 1 : gate + 1])


def _abort_drain() -> str:
    """The script's own abort_drain, verbatim."""
    lines = _lines()
    start = lines.index("abort_drain() {")
    return "\n".join(lines[start : lines.index("}", start) + 1])


def _swap_begins() -> str:
    """The line that marks the swap begun, which must sit right before it."""
    lines = _lines()
    swap = lines.index(_SWAP)
    assert lines[swap - 1] == "SWAPPING=1", (
        "SWAPPING=1 must be set immediately before the first swap_up"
    )
    return lines[swap - 1]


def _run(
    tmp: Path,
    then: str,
    *,
    compose_ups: int = 0,
    held: bool = False,
    dry: int = 0,
    pause_fails: bool = False,
    clear_fails: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    host = tmp / "host"
    host.mkdir()
    if held:
        (host / ".pit-stop.lock").mkdir()
        (host / ".pit-stop.lock" / "holder").write_text(
            "pid=4242 host=laptop user=someone started=2026-10-14T09:00:00Z tag=v1\n"
        )
    work = tmp / "work"
    work.mkdir()
    fail_true = 'if [ "$1" = true ]; then return 1; fi' if pause_fails else ":"
    fail_false = 'if [ "$1" = false ]; then return 1; fi' if clear_fails else ":"
    preamble = f"""
set -euo pipefail
TAG=v1.1.0-beta.1; VERSION=1.1.0-beta.1; DRY={dry}; HOST=fake-host; TMP={work}
COMPOSE_DIR={host}; T0=$(date +%s)
RECOVERY=""; RECOVERY_SHOWN=0
step() {{ printf '==> %s\\n' "$*"; }}
die() {{
    printf 'PIT STOP ABORTED: %s\\n' "$*" >&2
    if [ -n "$RECOVERY" ]; then printf '%s\\n' "$RECOVERY" >&2; RECOVERY_SHOWN=1; fi
    exit 1
}}
remote() {{
    echo "$*" >> {tmp}/remote_calls
    case "$*" in
    "ps -eo args"*) echo {compose_ups} ;;
    *) sh -c "$*" ;;
    esac
}}
maintenance() {{ echo "maintenance $1" >> {tmp}/maintenance_calls; {fail_true}; {fail_false}; }}
{_abort_drain()}
"""
    script = "\n".join([preamble, _lock_block(), _gate(), then])
    proc = subprocess.run(
        ["bash", "-c", script, str(_SCRIPT)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    calls = tmp / "maintenance_calls"
    remote = tmp / "remote_calls"
    return (
        proc,
        calls.read_text().splitlines() if calls.exists() else [],
        remote.read_text().splitlines() if remote.exists() else [],
    )


_ABORTS = [
    ('die "the drain failed"', 1),
    ("kill -TERM $$; sleep 5", 143),
    ("kill -INT $$; sleep 5", 130),
    ("false", 1),
]


@pytest.mark.parametrize(("then", "code"), _ABORTS)
def test_an_abort_before_the_swap_reopens_admission(tmp_path: Path, then: str, code: int) -> None:
    proc, maintenance, _ = _run(tmp_path, then)
    assert proc.returncode == code, proc.stderr
    assert maintenance == ["maintenance true", "maintenance false"]
    assert "admission is OPEN again" in proc.stderr
    assert not (tmp_path / "host" / ".pit-stop.lock").exists()
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize(("then", "code"), _ABORTS)
def test_an_abort_after_the_swap_began_leaves_admission_paused(
    tmp_path: Path, then: str, code: int
) -> None:
    """#1575: a build that failed verify never takes traffic."""
    swap = f'RECOVERY="RECOVERY: finish by hand"\n{_swap_begins()}\n{then}'
    proc, maintenance, _ = _run(tmp_path, swap)
    assert proc.returncode == code, proc.stderr
    assert maintenance == ["maintenance true"]
    assert f"admission is still PAUSED on purpose (code {code})" in proc.stderr
    # RECOVERY exactly once, whether die printed it or the trap had to.
    assert proc.stderr.count("RECOVERY: finish by hand") == 1
    assert not (tmp_path / "host" / ".pit-stop.lock").exists()


def test_a_failed_pause_put_is_still_undone(tmp_path: Path) -> None:
    """A PUT that persisted but failed in flight would otherwise stay shut."""
    proc, maintenance, _ = _run(tmp_path, "exit 0", pause_fails=True)
    assert proc.returncode == 1
    assert "could not pause admission" in proc.stderr
    assert maintenance == ["maintenance true", "maintenance false"]


def test_the_ungate_disarms_the_trap(tmp_path: Path) -> None:
    proc, maintenance, _ = _run(tmp_path, 'maintenance false ""\nGATED=0\nexit 0')
    assert proc.returncode == 0, proc.stderr
    assert maintenance == ["maintenance true", "maintenance false"]
    assert not (tmp_path / "host" / ".pit-stop.lock").exists()


def test_the_lock_names_its_pid_host_and_start(tmp_path: Path) -> None:
    proc, _, _ = _run(tmp_path, f"cat {tmp_path}/host/.pit-stop.lock/holder; exit 0")
    assert proc.returncode == 0, proc.stderr
    holder = proc.stdout
    for field in ("pid=", "host=", "started=", "tag=v1.1.0-beta.1"):
        assert field in holder, holder


def test_a_second_swapper_is_refused_with_the_holder(tmp_path: Path) -> None:
    proc, maintenance, _ = _run(tmp_path, "exit 0", held=True)
    assert proc.returncode == 1
    assert "another pit stop holds" in proc.stderr
    assert "pid=4242 host=laptop" in proc.stderr
    assert "started=2026-10-14T09:00:00Z" in proc.stderr
    assert maintenance == []
    # Its lock is not ours to remove.
    assert (tmp_path / "host" / ".pit-stop.lock" / "holder").exists()


def test_a_running_compose_up_is_never_interrupted(tmp_path: Path) -> None:
    proc, maintenance, remote = _run(tmp_path, "exit 0", compose_ups=1)
    assert proc.returncode == 1
    assert "a docker compose up is already running" in proc.stderr
    assert maintenance == []
    assert not any("mkdir" in call for call in remote)


def test_a_dry_run_takes_no_lock(tmp_path: Path) -> None:
    proc, _, remote = _run(tmp_path, "exit 0", dry=1)
    assert proc.returncode == 0, proc.stderr
    assert remote == []


def test_the_lock_is_taken_before_anything_ships_in_every_mode() -> None:
    """Two pit stops that each shipped and staged before either locked would
    each repoint the compose file under the other. The claim is top level
    (not inside a mode branch) and precedes the ship, the stage, the
    --stage-only exit, the --swap-only precheck and the gateway-only path."""
    lines = _lines()
    claim = lines.index(_CLAIM)
    for later in (
        'step "ship: docker save | docker load on $HOST"',
        'step "stage: back up the deployed compose and repoint $REPOINTS"',
        'if [ "$MODE" = "stage" ]; then',
        'if [ "$MODE" = "swap" ] && [ "$DRY" = 0 ]; then',
        'if [ "$SERVICE" = gateway ]; then',
    ):
        at = next(i for i, line in enumerate(lines) if line.strip() == later)
        assert claim < at, f"the lock is claimed after: {later}"


@pytest.mark.parametrize(
    ("clear_fails", "report"), [(False, "admission is OPEN again"), (True, "may still be PAUSED")]
)
def test_a_drain_abort_reports_the_clear_once(
    tmp_path: Path, clear_fails: bool, report: str
) -> None:
    """abort_drain clears the gate itself; the exit trap must not PUT and
    report a second time (a 503 used to print "still PAUSED" twice)."""
    proc, maintenance, _ = _run(tmp_path, 'abort_drain "the drain failed"', clear_fails=clear_fails)
    assert proc.returncode == 1
    assert maintenance == ["maintenance true", "maintenance false"]
    assert proc.stderr.count(report) == 1, proc.stderr
