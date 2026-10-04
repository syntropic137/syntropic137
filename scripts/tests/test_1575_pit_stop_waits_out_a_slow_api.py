"""A swap whose API is slow to turn healthy must not leave the gateway down (#1575).

beta.5: the new API spent ~2 minutes on a startup backfill, `compose up -d api
gateway` failed with "dependency failed to start: container syn137-api is
unhealthy", and the script exited there - admission paused, gateway `Created`,
nothing telling the operator how to finish.

These run the tail of pit_stop.sh - swap, verify, ungate - exactly as it is
written, with `remote` stubbed to play the host and `api` to play the API:
compose fails while the API is not yet healthy, the container health check
reports `starting` for a few polls, and /health answers with whatever phase the
test gives it. Running through verify is what covers READINESS (the pit stop
reopens admission only on "healthy", never on a 200) and RECOVERY (every abort
after the swap prints how to finish by hand, and what it prints works).
"""

from __future__ import annotations

import base64
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"
_START = "# Bring api + gateway up."
_VERIFY = 'step "verify: images, docker CLI, projections, build identity"'


def _tail() -> str:
    """From the swap to the end of the script: swap, verify, ungate."""
    lines = _SCRIPT.read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(_START)]
    assert len(starts) == 1 and any(line.strip() == _VERIFY for line in lines[starts[0] :]), (
        f"could not find the swap and verify steps in {_SCRIPT.name} ({_START!r}, {_VERIFY!r}); "
        f"if they moved, this test is no longer running them"
    )
    return "\n".join(lines[starts[0] :])


def _function(name: str) -> str:
    """A function from the script verbatim, so verify reads /health as it does."""
    lines = _SCRIPT.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _run_swap(
    tmp: Path,
    *,
    health: list[str],
    ready: tuple[str, ...] = ("healthy",),
    ssh_down_from: str | None = None,
    compose_fails_until_healthy: bool = True,
    timeout: int = 900,
    api_url: str = "http://fake/api/v1",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """``health`` is what successive container health polls report, as
    "<status> <restarts> <health>"; ``ready`` is what successive GET /health
    calls answer as ``status``. In both the last entry repeats forever.
    ``ssh_down_from``: from the first remote command containing it, every
    remote command fails as an unreachable host does."""
    (tmp / "health").write_text("\n".join(health) + "\n")
    (tmp / "ready").write_text("\n".join(ready) + "\n")
    (tmp / "ssh_down_from").write_text(ssh_down_from or "")
    stub = f"""
nth() {{  # nth <file> <counter>: the next line of <file>, the last one repeating
    n=$(cat {tmp}/$2 2>/dev/null || echo 0); echo $((n + 1)) > {tmp}/$2
    total=$(wc -l < {tmp}/$1)
    sed -n "$(( n + 1 < total ? n + 1 : total ))p" {tmp}/$1
}}
remote() {{
    down=$(cat {tmp}/ssh_down_from)
    if [ -e {tmp}/ssh_down ] || {{ [ -n "$down" ] && case "$*" in *"$down"*) true ;; *) false ;; esac; }}; then
        touch {tmp}/ssh_down
        echo "ssh: connect to host fake-host port 22: Connection timed out" >&2; return 255
    fi
    case "$*" in
    *"docker inspect syn137-api --format '{{{{.State.Status}}"*) nth health polls ;;
    *"docker compose"*)
        echo "$*" >> {tmp}/compose_calls
        last=$(sed -n "$(cat {tmp}/polls 2>/dev/null || echo 1)p" {tmp}/health)
        if [ {int(compose_fails_until_healthy)} = 1 ] && [ "${{last##* }}" != healthy ]; then
            echo "dependency failed to start: container syn137-api is unhealthy"; return 1
        fi
        echo " Container syn137-gateway  Started" ;;
    *"docker image inspect ghcr.io/syntropic137/syn-api:"*) echo sha256:api ;;
    *"docker image inspect ghcr.io/syntropic137/syn-gateway:"*) echo sha256:gateway ;;
    *"docker inspect syn137-api --format '{{{{.Image}}}}'"*) echo sha256:api ;;
    *"docker inspect syn137-gateway --format '{{{{.Image}}}}'"*) echo sha256:gateway ;;
    *"--format '{{{{.State.Running}}}}'"*) echo true ;;
    *"docker exec syn137-api"*) echo /usr/bin/docker ;;
    *) echo "unexpected remote: $*" >&2; return 99 ;;
    esac
}}
api() {{
    case "$1" in
    /health)
        s=$(nth ready health_calls)
        printf '{{"status": "%s", "subscription": {{"status": "healthy", "is_catching_up": false, "lag": 0}}}}' "$s" > "$2" ;;
    /version) printf '{{"image_tag": "%s", "commit": "abc123"}}' "$TAG" > "$2" ;;
    *) return 22 ;;
    esac
}}
maintenance() {{ echo "maintenance $1" >> {tmp}/maintenance_calls; }}
"""
    preamble = f"""
set -euo pipefail
TAG=v0.33.2-beta.5; VERSION=0.33.2-beta.5; DRY=0; HOST=fake-host; API={api_url}
COMPOSE_DIR=/root/.syntropic137; COMPOSE=docker-compose.syntropic137.yaml; TMP={tmp}
API_READY_TIMEOUT={timeout}; RECOVERY=""; T0=$(date +%s)
step() {{ printf '==> %s\\n' "$*"; }}
die() {{
    printf 'PIT STOP ABORTED: %s\\n' "$*" >&2
    if [ -n "$RECOVERY" ]; then printf '%s\\n' "$RECOVERY" >&2; fi
    exit 1
}}
run() {{ "$@"; }}
sleep() {{ :; }}
{stub}
{_function("projections_healthy")}
"""
    proc = subprocess.run(
        ["bash", "-c", preamble + _tail(), str(_SCRIPT)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    calls_file = tmp / "compose_calls"
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    return proc, calls


def _maintenance_calls(tmp: Path) -> list[str]:
    calls = tmp / "maintenance_calls"
    return calls.read_text().splitlines() if calls.exists() else []


def _recovery_was_printed(proc: subprocess.CompletedProcess[str]) -> bool:
    return "admission is still PAUSED" in proc.stderr and "/maintenance" in proc.stderr


def test_compose_fails_on_an_unhealthy_api_then_succeeds_once_it_is_healthy(
    tmp_path: Path,
) -> None:
    proc, calls = _run_swap(
        tmp_path, health=["running 0 starting", "running 0 unhealthy", "running 0 healthy"]
    )
    assert proc.returncode == 0, proc.stderr
    assert "PIT STOP DONE" in proc.stdout
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
    assert "PIT STOP DONE" not in proc.stdout
    assert len(calls) == 1, "no second compose up for an API that never got healthy"
    assert "did not become healthy within 60s" in proc.stderr
    # Never a silent half-swap: every step to finish by hand is named.
    assert "admission is still PAUSED" in proc.stderr
    assert "up -d gateway" in proc.stderr
    assert "/version" in proc.stderr
    assert "PUT" in proc.stderr and "/maintenance" in proc.stderr
    assert '"active": false' in proc.stderr
    assert _maintenance_calls(tmp_path) == []


def test_a_crash_loop_is_not_waited_out(tmp_path: Path) -> None:
    proc, calls = _run_swap(
        tmp_path, health=["running 0 starting", "restarting 1 unhealthy"], timeout=900
    )
    assert proc.returncode != 0
    assert "crash loop" in proc.stdout
    assert len(calls) == 1
    # It gave up on the first restart, not after the 900s deadline.
    assert "[+15s]" in proc.stdout and "[+30s]" not in proc.stdout


def test_admission_reopens_only_once_health_says_healthy(tmp_path: Path) -> None:
    proc, _ = _run_swap(
        tmp_path, health=["running 0 healthy"], ready=("starting", "starting", "healthy")
    )
    assert proc.returncode == 0, proc.stderr
    assert "PIT STOP DONE" in proc.stdout
    assert "/health status: starting" in proc.stdout
    assert "/health status: healthy" in proc.stdout
    assert _maintenance_calls(tmp_path) == ["maintenance false"]


def test_a_200_that_says_failed_is_not_ready(tmp_path: Path) -> None:
    """/health answers 200 "failed" between a late startup failure and the
    process exiting (#1575). A pit stop that took any 200 for ready would
    reopen admission on a dying process."""
    proc, _ = _run_swap(tmp_path, health=["running 0 healthy"], ready=("failed",), timeout=60)
    assert proc.returncode != 0
    assert "the API did not finish starting within 60s" in proc.stderr
    assert _recovery_was_printed(proc)
    assert _maintenance_calls(tmp_path) == [], "admission must stay paused"


@pytest.mark.parametrize(
    "unreachable_at",
    [
        "docker image inspect ghcr.io/syntropic137/syn-api:",
        "docker inspect syn137-api --format '{{.Image}}'",
        "docker inspect syn137-gateway --format '{{.State.Running}}'",
        "docker exec syn137-api",
    ],
)
def test_losing_the_host_during_verify_still_prints_the_recovery(
    tmp_path: Path, unreachable_at: str
) -> None:
    """Admission is paused and the containers are new: an ssh failure here must
    abort through die() and say how to finish, never exit silently on set -e."""
    proc, _ = _run_swap(tmp_path, health=["running 0 healthy"], ssh_down_from=unreachable_at)
    assert proc.returncode != 0
    assert "PIT STOP ABORTED" in proc.stderr, proc.stderr
    assert _recovery_was_printed(proc)
    assert _maintenance_calls(tmp_path) == []


class _MaintenanceEndpoint(BaseHTTPRequestHandler):
    bodies: ClassVar[list[bytes]] = []
    auths: ClassVar[list[str]] = []

    def do_PUT(self) -> None:
        self.auths.append(self.headers["Authorization"])
        self.bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args: object) -> None:
        pass


def test_the_printed_recovery_reopens_admission_when_pasted(tmp_path: Path) -> None:
    """Run the PUT line exactly as an operator would paste it, against a fake
    API, and require the body that arrives to be the JSON that clears the gate."""
    server = HTTPServer(("127.0.0.1", 0), _MaintenanceEndpoint)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api_url = f"http://127.0.0.1:{server.server_port}/api/v1"
        proc, _ = _run_swap(tmp_path, health=["running 0 starting"], timeout=15, api_url=api_url)
        assert proc.returncode != 0
        (put,) = [line for line in proc.stderr.splitlines() if "-X PUT" in line]
        pasted = subprocess.run(
            ["bash", "-c", put.strip()],
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "SYN_API_PASSWORD": "pw"},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert pasted.returncode == 0, pasted.stderr
    finally:
        server.shutdown()
    (body,) = _MaintenanceEndpoint.bodies
    assert json.loads(body) == {"active": False, "reason": "", "actor": "manual"}
    # The one thing in it left for the shell to fill in is the password.
    assert _MaintenanceEndpoint.auths == ["Basic " + base64.b64encode(b"admin:pw").decode()]
