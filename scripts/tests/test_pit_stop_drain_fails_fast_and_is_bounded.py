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
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

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
_LONG_ROW: dict[str, str] = {
    "workflow_execution_id": _LONG_RUN,
    "workflow_name": "repair-round",
    "started_at": "2026-10-07T10:00:00Z",
}

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
            {
                "projection": "workflow_execution_list",
                "execution_id": _DROPPED_A,
                "global_nonce": 7,
            },
            {"projection": "workflow_executions", "execution_id": _DROPPED_B, "global_nonce": 9},
        ],
    },
}


@dataclass
class _Host:
    """``counts`` are successive status_counts bodies, the last repeating.

    ``health_delay`` holds every /health answer back, in seconds; ``running``
    is the whole running collection, served in the pages the client asks for.
    """

    health: dict[str, object]
    counts: list[dict[str, int]]
    health_delay: float = 0.0
    running: list[dict[str, str]] = field(default_factory=lambda: [_LONG_ROW])
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
                time.sleep(state.health_delay)
                self._answer(state.health)
            elif self.path == "/api/v1/executions?page_size=1":
                counts = state.counts[min(state.count_reads, len(state.counts) - 1)]
                state.count_reads += 1
                self._answer({"executions": [], "total": 0, "status_counts": counts})
            elif self.path.startswith("/api/v1/executions?status=running"):
                query = parse_qs(urlsplit(self.path).query)
                page = int(query.get("page", ["1"])[0])
                size = min(int(query.get("page_size", ["50"])[0]), 200)  # the API's maximum
                rows = state.running[(page - 1) * size : page * size]
                self._answer({"executions": rows, "total": len(state.running)})
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


def _assignments(name: str) -> list[str]:
    """Every top-level assignment of ``name`` in the script, in order."""
    return [line for line in _SCRIPT.read_text().splitlines() if line.startswith(f"{name}=")]


def _assignment(name: str) -> str:
    hits = _assignments(name)
    assert len(hits) == 1, f"expected one assignment of {name} in {_SCRIPT.name}"
    return hits[0]


def _gate_and_drain() -> str:
    """The script from the gate step through the drain and its guard, as written."""
    lines = _SCRIPT.read_text().splitlines()
    start = lines.index(_GATE_START)
    end = lines.index("drain_loop", start)
    assert lines[end + 1].startswith('[ "$DRAINED" = 1 ] || abort_drain'), (
        "the drain lost its guard"
    )
    return "\n".join(lines[start : end + 2])


def _run(
    tmp: Path, api: str, *, budget: int | str, override: str = ""
) -> subprocess.CompletedProcess[str]:
    """``budget`` is SYN_PIT_DRAIN_TIMEOUT, parsed by the script's own lines.

    ``override`` runs after that parsing, to reach states it now forbids.
    """
    functions = [
        "api_curl",
        "api",
        "maintenance",
        "mono_now",
        "left",
        "cap",
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
            *_assignments("DRAIN_TIMEOUT"),
            override,
            _assignment("DROPPED_RUNBOOK"),
            _assignment("DRAINED"),
            "step() { printf '==> %s\\n' \"$*\"; }",
            "die() { printf 'PIT STOP ABORTED: %s\\n' \"$*\" >&2; exit 1; }",
            "sleep() { :; }",
            *(_definition(name) for name in functions),
        ]
    )
    return subprocess.run(
        ["bash", "-c", preamble + "\n" + _gate_and_drain() + "\necho DRAINED-AND-CONTINUING"],
        env={
            "PATH": os.environ["PATH"],
            "SYN_API_PASSWORD": _PASSWORD,
            "SYN_PIT_DRAIN_TIMEOUT": str(budget),
        },
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

    # Printed AT THE GATE, before the drain starts: the drain's own checks print
    # the same counts, so only the order shows the gate read them.
    at_gate = proc.stdout.split("==> drain:")[0]
    assert "queued=2 running=1" in at_gate
    assert proc.returncode == 0, proc.stderr


def test_the_default_budget_is_45_minutes() -> None:
    assert _assignments("DRAIN_TIMEOUT")[0] == 'DRAIN_TIMEOUT="${SYN_PIT_DRAIN_TIMEOUT:-2700}"'


def test_a_slow_read_cannot_carry_the_drain_past_its_budget(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    """A 1s budget and a /health that answers in 3s, with terminal counts.

    Uncapped, the late answer arrived after the budget and the drain returned
    success from it (4.66s, rc 0). Capped, the read times out inside the budget
    and the drain stops undrained.
    """
    state, api = host
    state.health_delay = 3.0
    state.counts = [{"completed": 4}]

    started = time.monotonic()
    proc = _run(tmp_path, api, budget=1)
    elapsed = time.monotonic() - started

    assert proc.returncode != 0
    assert "DRAINED-AND-CONTINUING" not in proc.stdout
    assert "drain budget of 1s spent" in proc.stderr
    assert elapsed < 3.0, f"the drain took {elapsed:.2f}s on a 1s budget"
    assert _admission_puts(state) == [True, False]
    _no_secret_leaked(proc)


def test_a_spent_budget_lists_every_running_execution_past_one_page(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    state.counts = [{"running": 201}]
    state.running = [
        {
            "workflow_execution_id": f"exec-{i:03d}",
            "workflow_name": "repair-round",
            "started_at": "2026-10-07T10:00:00Z",
        }
        for i in range(201)
    ]

    proc = _run(tmp_path, api, budget=0)

    assert proc.returncode != 0
    assert "STILL RUNNING (201)" in proc.stdout
    missing = [
        r["workflow_execution_id"]
        for r in state.running
        if r["workflow_execution_id"] not in proc.stdout
    ]
    assert not missing, f"not listed: {missing}"
    assert proc.stdout.count("STILL RUNNING") == 1
    _no_secret_leaked(proc)


def test_a_leading_zero_budget_is_read_in_base_ten(tmp_path: Path, host: tuple[_Host, str]) -> None:
    """``08`` passes the digits-only check; read as octal it broke the drain."""
    state, api = host
    state.counts = [{"running": 1}, {"running": 1}, {"completed": 4}]

    proc = _run(tmp_path, api, budget="08")

    assert proc.returncode == 0, proc.stderr
    assert "value too great for base" not in proc.stderr
    assert "budget 8s" in proc.stdout
    assert "(drained)" in proc.stdout
    assert _admission_puts(state) == [True]


def test_a_drain_that_errors_out_never_continues_and_reopens_admission(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    """Bash abandons a function on an arithmetic error WITHOUT ``set -e``.

    Force one past the parsing, with a busy platform: whatever breaks inside
    the drain, nothing undrained may continue to the swap.
    """
    state, api = host
    state.counts = [{"running": 1}]

    proc = _run(tmp_path, api, budget=2700, override="DRAIN_TIMEOUT=08")

    assert "value too great for base" in proc.stderr
    assert proc.returncode != 0
    assert "DRAINED-AND-CONTINUING" not in proc.stdout
    assert "without a drained verdict" in proc.stderr
    assert _admission_puts(state) == [True, False]
    _no_secret_leaked(proc)
