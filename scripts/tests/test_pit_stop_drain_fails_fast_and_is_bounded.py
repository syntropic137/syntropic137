"""The pit stop's drain says WHY it waits, and stops when waiting cannot help.

PC-115 (2026-10-07): the drain printed "read path is not at the event-store
head yet" 135 times over ~2.25h with admission paused, while /health said
`subscription.status = dropped_events` (#1696). That status never heals by
waiting, and the status itself was sent to /dev/null.

PC-114 (same day): one long repair round held the whole drain for ~2h under a
3h default budget, and the budget's expiry named nothing still running.

These run the gate and the drain of pit_stop.sh exactly as written, with the
script's own functions, against a fake syn-api served over real HTTP.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"
_PASSWORD = "s3cret-drain-pw"
_GATE_START = 'step "gate: pausing execution admission for the rest of the pit stop"'
_RUNBOOK = "docs/runbooks/repair-dropped-execution-start.md"
_DROPPED_A = "exec-dropped00000a"
_DROPPED_B = "exec-dropped00000b"
_LONG_RUN = "exec-longrepair0001"

_HEALTHY: dict[str, object] = {
    "status": "healthy",
    "subscription": {"status": "healthy", "is_catching_up": False, "lag": 0},
}
_DROPPED: dict[str, object] = {
    "status": "degraded",
    "degraded_reasons": ["projection_dropped_event"],
    "subscription": {
        "status": "dropped_events",
        "is_catching_up": False,
        "lag": 0,
        "unapplied_starts": [
            {"projection": "workflow_executions", "execution_id": _DROPPED_A, "global_nonce": 7},
            {"projection": "workflow_execution_list", "execution_id": _DROPPED_A, "global_nonce": 7},
            {"projection": "workflow_executions", "execution_id": _DROPPED_B, "global_nonce": 9},
        ],
    },
}


@dataclass
class _Host:
    """``counts`` are successive status_counts bodies, the last repeating."""

    health: dict[str, object]
    counts: list[dict[str, int]]
    count_reads: int = 0
    requests: list[tuple[str, str, bytes]] = field(default_factory=list)


@pytest.fixture
def host() -> Iterator[tuple[_Host, str]]:
    state = _Host(health=_HEALTHY, counts=[{"completed": 3}])

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self) -> bytes:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            state.requests.append((self.command, self.path, body))
            return body

        def do_PUT(self) -> None:
            body = json.loads(self._record())
            self._answer({"active": body["active"], "reason": body["reason"]})

        def do_GET(self) -> None:
            self._record()
            if self.path == "/api/v1/health":
                self._answer(state.health)
            elif self.path == "/api/v1/executions?page_size=1":
                counts = state.counts[min(state.count_reads, len(state.counts) - 1)]
                state.count_reads += 1
                self._answer({"executions": [], "total": 0, "status_counts": counts})
            elif self.path.startswith("/api/v1/executions?status=running"):
                row = {
                    "workflow_execution_id": _LONG_RUN,
                    "workflow_name": "repair-round",
                    "started_at": "2026-10-07T10:00:00Z",
                }
                self._answer({"executions": [row], "total": 1})
            else:
                self.send_error(404)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/api/v1"
    finally:
        server.shutdown()


def _definition(name: str) -> str:
    """A function from the script verbatim, one-line or block."""
    lines = _SCRIPT.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    if lines[start].rstrip().endswith("}"):
        return lines[start]
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _assignment(name: str) -> str:
    lines = _SCRIPT.read_text().splitlines()
    hits = [line for line in lines if line.startswith(f"{name}=")]
    assert len(hits) == 1, f"expected one assignment of {name} in {_SCRIPT.name}"
    return hits[0]


def _gate_and_drain() -> str:
    """The script from the gate step through the drain, as written."""
    lines = _SCRIPT.read_text().splitlines()
    start = lines.index(_GATE_START)
    end = lines.index("drain_loop", start)
    return "\n".join(lines[start : end + 1])


def _run(tmp: Path, api: str, *, budget: int) -> subprocess.CompletedProcess[str]:
    functions = [
        "api_curl",
        "api",
        "maintenance",
        "mono_now",
        "projections_healthy",
        "drained",
        "status_counts",
        "running_executions",
        "abort_drain",
        "drain_loop",
    ]
    preamble = "\n".join(
        [
            "set -euo pipefail",
            f"VERSION=0.40.0-beta.1; DRY=0; API={api}; TMP={tmp}; RECOVERY=''",
            f"DRAIN_TIMEOUT={budget}",
            _assignment("DROPPED_RUNBOOK"),
            "step() { printf '==> %s\\n' \"$*\"; }",
            "die() { printf 'PIT STOP ABORTED: %s\\n' \"$*\" >&2; exit 1; }",
            "sleep() { :; }",
            *(_definition(name) for name in functions),
        ]
    )
    return subprocess.run(
        ["bash", "-c", preamble + "\n" + _gate_and_drain() + "\necho DRAINED-AND-CONTINUING"],
        env={"PATH": os.environ["PATH"], "SYN_API_PASSWORD": _PASSWORD},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _admission_puts(state: _Host) -> list[bool]:
    return [json.loads(body)["active"] for method, _, body in state.requests if method == "PUT"]


def _no_secret_leaked(proc: subprocess.CompletedProcess[str]) -> None:
    assert _PASSWORD not in proc.stdout + proc.stderr


def test_dropped_events_fail_fast_naming_the_runs_and_the_runbook(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    state.health = _DROPPED
    state.counts = [{"running": 1}]

    proc = _run(tmp_path, api, budget=2700)

    out = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "DRAINED-AND-CONTINUING" not in out
    assert "dropped_events" in proc.stdout
    assert "projection_dropped_event" in proc.stdout
    assert _DROPPED_A in proc.stdout
    assert _DROPPED_B in proc.stdout
    assert _RUNBOOK in proc.stderr
    # One /health read: it did not wait for something waiting cannot fix.
    assert [p for _, p, _ in state.requests].count("/api/v1/health") == 1
    # Paused at the gate, re-opened before the abort, and the abort says so.
    assert _admission_puts(state) == [True, False]
    assert "admission is OPEN again" in proc.stderr
    _no_secret_leaked(proc)


def test_a_spent_budget_stops_with_the_running_list_and_cancels_nothing(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    state.counts = [{"queued": 2, "running": 1, "completed": 5}]

    proc = _run(tmp_path, api, budget=0)

    assert proc.returncode != 0
    assert "DRAINED-AND-CONTINUING" not in proc.stdout
    assert "STILL RUNNING (1)" in proc.stdout
    assert _LONG_RUN in proc.stdout
    assert "drain budget of 0s spent" in proc.stderr
    assert "WAIT" in proc.stderr
    assert "INTERRUPT" in proc.stderr
    assert not [r for r in state.requests if r[0] == "POST"], "the pit stop cancelled work"
    assert _admission_puts(state) == [True, False]
    _no_secret_leaked(proc)


def test_a_healthy_drain_passes_unchanged_and_keeps_admission_paused(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    # Busy at the gate, busy on the first check, quiet on the second.
    state.counts = [{"queued": 2, "running": 1}, {"running": 1}, {"completed": 4}]

    proc = _run(tmp_path, api, budget=2700)

    assert proc.returncode == 0, proc.stderr
    assert "DRAINED-AND-CONTINUING" in proc.stdout
    assert "(drained)" in proc.stdout
    assert _admission_puts(state) == [True]
    assert "PIT STOP ABORTED" not in proc.stderr
    _no_secret_leaked(proc)


def test_every_check_prints_the_subscription_status_and_reasons(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    state.health = {
        "status": "degraded",
        "degraded_reasons": ["projection_lagging"],
        "subscription": {"status": "catching_up", "is_catching_up": True, "lag": 40},
    }

    proc = _run(tmp_path, api, budget=0)

    assert "'status': 'catching_up'" in proc.stdout
    assert "projection_lagging" in proc.stdout
    assert "read path is not at the event-store head yet" in proc.stdout
    _no_secret_leaked(proc)


def test_the_gate_prints_queued_versus_running(tmp_path: Path, host: tuple[_Host, str]) -> None:
    state, api = host
    state.counts = [{"queued": 2, "running": 1}, {"completed": 4}]

    proc = _run(tmp_path, api, budget=2700)

    gate_line = next(line for line in proc.stdout.splitlines() if "queued=" in line)
    assert "queued=2 running=1" in gate_line
    assert proc.returncode == 0, proc.stderr


def test_the_default_budget_is_45_minutes() -> None:
    assert _assignment("DRAIN_TIMEOUT") == 'DRAIN_TIMEOUT="${SYN_PIT_DRAIN_TIMEOUT:-2700}"'
