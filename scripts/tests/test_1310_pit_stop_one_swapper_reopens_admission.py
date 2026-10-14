"""One swapper at a time, never under a running compose up, and every exit
after the gate re-opens admission (#1310 1.6).

These run the script's own block, from its lock to the gate, with ``remote``
playing the host and ``maintenance`` recording every PUT, then end the run the
ways a pit stop ends: a ``die``, a TERM, an INT, and the ungate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"
_START = "# ONE SWAPPER AT A TIME"
_GATE = 'maintenance true "pit stop $VERSION"'


def _block() -> str:
    """From the lock through the gate, verbatim."""
    lines = _SCRIPT.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(_START))
    gate = next(i for i, line in enumerate(lines) if line.startswith(_GATE))
    assert lines[gate + 1] == "GATED=1", "the gate must arm the exit trap on its next line"
    return "\n".join(lines[start : gate + 2])


def _run(
    tmp: Path, then: str, *, compose_ups: int = 0, held: bool = False, dry: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    host = tmp / "host"
    host.mkdir()
    if held:
        (host / ".pit-stop.lock").mkdir()
        (host / ".pit-stop.lock" / "holder").write_text("someone@else v1\n")
    work = tmp / "work"
    work.mkdir()
    preamble = f"""
set -euo pipefail
TAG=v1.1.0-beta.1; VERSION=1.1.0-beta.1; DRY={dry}; HOST=fake-host; TMP={work}
COMPOSE_DIR={host}; T0=$(date +%s)
step() {{ printf '==> %s\\n' "$*"; }}
die() {{ printf 'PIT STOP ABORTED: %s\\n' "$*" >&2; exit 1; }}
remote() {{
    echo "$*" >> {tmp}/remote_calls
    case "$*" in
    "ps -eo args"*) echo {compose_ups} ;;
    *) sh -c "$*" ;;
    esac
}}
maintenance() {{ echo "maintenance $1" >> {tmp}/maintenance_calls; }}
"""
    proc = subprocess.run(
        ["bash", "-c", preamble + _block() + "\n" + then, str(_SCRIPT)],
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


@pytest.mark.parametrize(
    ("then", "code"),
    [
        ('die "verify failed after the swap"', 1),
        ("kill -TERM $$; sleep 5", 143),
        ("kill -INT $$; sleep 5", 130),
        ("false", 1),
    ],
)
def test_every_abort_after_the_gate_reopens_admission(tmp_path: Path, then: str, code: int) -> None:
    proc, maintenance, _ = _run(tmp_path, then)
    assert proc.returncode == code, proc.stderr
    assert maintenance == ["maintenance true", "maintenance false"]
    assert not (tmp_path / "host" / ".pit-stop.lock").exists()
    assert not (tmp_path / "work").exists()


def test_the_ungate_disarms_the_trap(tmp_path: Path) -> None:
    proc, maintenance, _ = _run(tmp_path, 'maintenance false ""\nGATED=0\nexit 0')
    assert proc.returncode == 0, proc.stderr
    assert maintenance == ["maintenance true", "maintenance false"]
    assert not (tmp_path / "host" / ".pit-stop.lock").exists()


def test_a_second_swapper_is_refused_before_the_gate(tmp_path: Path) -> None:
    proc, maintenance, _ = _run(tmp_path, "exit 0", held=True)
    assert proc.returncode == 1
    assert "another pit stop holds" in proc.stderr and "someone@else" in proc.stderr
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
    assert not any("mkdir" in call for call in remote)
