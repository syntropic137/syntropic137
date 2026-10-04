"""A swap whose API is slow to turn healthy must not leave the gateway down (#1575).

beta.5: the new API spent ~2 minutes on a startup backfill, `compose up -d api
gateway` failed with "dependency failed to start: container syn137-api is
unhealthy", and the script exited there - admission paused, gateway `Created`,
nothing telling the operator how to finish.

These run the swap block exactly as pit_stop.sh writes it, with `remote` stubbed
to play the host: compose fails while the API is not yet healthy, and the API
reports `starting` for a few polls before `healthy`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"
_START = "# Bring api + gateway up."
_END = 'step "verify: images, docker CLI, projections, build identity"'


def _swap_block() -> str:
    lines = _SCRIPT.read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(_START)]
    ends = [i for i, line in enumerate(lines) if line.strip() == _END]
    assert len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0], (
        f"could not find the swap block in {_SCRIPT.name} between {_START!r} and {_END!r}; "
        f"if it moved, this test is no longer running it"
    )
    return "\n".join(lines[starts[0] : ends[0]])


def _run_swap(
    tmp: Path, *, health: list[str], compose_fails_until_healthy: bool = True, timeout: int = 900
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """``health`` is what successive `docker inspect` polls report, as
    "<status> <restarts> <health>"; the last entry repeats forever."""
    (tmp / "health").write_text("\n".join(health) + "\n")
    stub = f"""
remote() {{
    case "$*" in
    *"docker inspect syn137-api"*)
        n=$(cat {tmp}/polls 2>/dev/null || echo 0); echo $((n + 1)) > {tmp}/polls
        total=$(wc -l < {tmp}/health)
        sed -n "$(( n + 1 < total ? n + 1 : total ))p" {tmp}/health ;;
    *"docker compose"*)
        echo "$*" >> {tmp}/compose_calls
        last=$(sed -n "$(cat {tmp}/polls 2>/dev/null || echo 1)p" {tmp}/health)
        if [ {int(compose_fails_until_healthy)} = 1 ] && [ "${{last##* }}" != healthy ]; then
            echo "dependency failed to start: container syn137-api is unhealthy"; return 1
        fi
        echo " Container syn137-gateway  Started" ;;
    *) echo "unexpected remote: $*" >&2; return 99 ;;
    esac
}}
"""
    preamble = f"""
set -euo pipefail
TAG=v0.33.2-beta.5; VERSION=0.33.2-beta.5; DRY=0; HOST=fake-host; API=http://fake/api/v1
COMPOSE_DIR=/root/.syntropic137; COMPOSE=docker-compose.syntropic137.yaml; TMP={tmp}
API_READY_TIMEOUT={timeout}; RECOVERY=""
step() {{ printf '==> %s\\n' "$*"; }}
die() {{
    printf 'PIT STOP ABORTED: %s\\n' "$*" >&2
    if [ -n "$RECOVERY" ]; then printf '%s\\n' "$RECOVERY" >&2; fi
    exit 1
}}
run() {{ "$@"; }}
sleep() {{ :; }}
api() {{ return 1; }}
{stub}
"""
    proc = subprocess.run(
        ["bash", "-c", preamble + _swap_block() + "\necho SWAP_DONE\n", str(_SCRIPT)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    calls_file = tmp / "compose_calls"
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    return proc, calls


def test_compose_fails_on_an_unhealthy_api_then_succeeds_once_it_is_healthy(
    tmp_path: Path,
) -> None:
    proc, calls = _run_swap(
        tmp_path, health=["running 0 starting", "running 0 unhealthy", "running 0 healthy"]
    )
    assert proc.returncode == 0, proc.stderr
    assert "SWAP_DONE" in proc.stdout
    # Once as the swap, once more for the dependents after the API is healthy.
    assert len(calls) == 2
    assert all("up -d api gateway" in c for c in calls)
    assert "waiting up to 900s for syn137-api" in proc.stdout
    assert "health=healthy" in proc.stdout


def test_a_swap_that_works_first_time_does_not_wait(tmp_path: Path) -> None:
    proc, calls = _run_swap(tmp_path, health=["running 0 healthy"])
    assert proc.returncode == 0, proc.stderr
    assert len(calls) == 1
    assert "waiting up to" not in proc.stdout


def test_an_api_that_never_turns_healthy_aborts_with_the_manual_recovery(
    tmp_path: Path,
) -> None:
    proc, calls = _run_swap(tmp_path, health=["running 0 starting"], timeout=60)
    assert proc.returncode != 0
    assert "SWAP_DONE" not in proc.stdout
    assert len(calls) == 1, "no second compose up for an API that never got healthy"
    assert "did not become healthy within 60s" in proc.stderr
    # Never a silent half-swap: every step to finish by hand is named.
    assert "admission is still PAUSED" in proc.stderr
    assert "up -d gateway" in proc.stderr
    assert "/version" in proc.stderr
    assert "PUT" in proc.stderr and "/maintenance" in proc.stderr
    assert '\\"active\\": false' in proc.stderr or '"active": false' in proc.stderr


def test_a_crash_loop_is_not_waited_out(tmp_path: Path) -> None:
    proc, calls = _run_swap(
        tmp_path, health=["running 0 starting", "restarting 1 unhealthy"], timeout=900
    )
    assert proc.returncode != 0
    assert "crash loop" in proc.stdout
    assert len(calls) == 1
    # It gave up on the first restart, not after the 900s deadline.
    assert "[+15s]" in proc.stdout and "[+30s]" not in proc.stdout
