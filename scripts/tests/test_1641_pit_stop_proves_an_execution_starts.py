"""The pit stop declares DONE only once a real execution has a PHASE running (#1641).

beta.8 and beta.9 passed every pit-stop check while no execution could start:
every direct start was dropped as a duplicate. The check that would have caught
it was "last check is yours: dispatch one real workflow", and nobody did.

These run the tail of pit_stop.sh - ungate, probe, DONE - exactly as written,
against a fake API served over real HTTP, so the script's own `api`, `api_post`
and `maintenance` make the requests and the fake answers them the way syn-api
does: POST /workflows/{id}/execute, GET /executions/{id} with `.phases[].status`,
POST /executions/{id}/cancel.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"
_START = "# AFTER verify, deliberately."
_PASSWORD = "s3cret-pit-pw"
_PROBE_ID = "exec-probe0000001"
# A deadline a test does not expect to reach. The fake answers at once, so a
# test that ends before it pays nothing for it, but every poll spawns curl and
# python3, and on a loaded 2-CPU host a 3s deadline passed before the fourth
# read of a probe that was about to report running. A test that needs a
# deadline to PASS says so with an explicit, short one.
_UNREACHED = 30


@dataclass
class _Host:
    """What the fake API answers. ``details`` are successive GET bodies for the
    probe, the last repeating; None is a 404. Once the first cancel request
    arrives, GET answers from ``after_cancel`` instead, when it is given.

    Cancel answers the way syn-api does since #1650 (PR #1651): 404 for an id
    GET does not know; for a start still ``queued`` it WITHDRAWS the request,
    answers 200 ``state=cancelled``, and GET then reports ``cancelled`` with no
    phases; for a started run it cancels it, and GET reports ``cancelled``.
    ``cancel_lands=False`` is a cancel that answers 200 and changes nothing.
    """

    details: list[dict[str, object] | None]
    after_cancel: list[dict[str, object] | None] | None = None
    dispatch_status: int = 200
    cancel_lands: bool = True
    get_delay: float = 0.0
    current: dict[str, object] | None = None
    cancel_seen: bool = False
    requests: list[tuple[str, str, bytes]] = field(default_factory=list)
    auths: set[str] = field(default_factory=set)
    gets: int = 0
    cancelled: bool = False
    withdrawn: bool = False


def _detail(status: str, *phases: str) -> dict[str, object]:
    return {
        "workflow_execution_id": _PROBE_ID,
        "status": status,
        "phases": [{"phase_id": "heartbeat", "status": p} for p in phases],
    }


@pytest.fixture
def host() -> Iterator[tuple[_Host, str]]:
    state = _Host(details=[])

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, code: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self) -> bytes:
            state.auths.add(self.headers.get("Authorization", ""))
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            state.requests.append((self.command, self.path, body))
            return body

        def do_PUT(self) -> None:
            body = json.loads(self._record())
            self._answer(200, {"active": body["active"], "reason": body["reason"]})

        def do_POST(self) -> None:
            self._record()
            if self.path == "/api/v1/workflows/telemetry-lag-probe-v1/execute":
                if state.dispatch_status != 200:
                    self._answer(state.dispatch_status, {"detail": "nope"})
                    return
                self._answer(200, {"execution_id": _PROBE_ID, "workflow_id": "x"})
            elif self.path == f"/api/v1/executions/{_PROBE_ID}/cancel":
                if not state.cancel_seen and state.after_cancel is not None:
                    state.details, state.gets = state.after_cancel, 0
                state.cancel_seen = True
                if state.current is None:
                    self._answer(404, {"detail": "Execution not found"})
                    return
                if state.cancel_lands:
                    state.cancelled = True
                    state.withdrawn = state.current.get("status") == "queued"
                self._answer(
                    200, {"success": True, "execution_id": _PROBE_ID, "state": "cancelled"}
                )
            else:
                self._answer(404, {"detail": "unknown"})

        def do_GET(self) -> None:
            self._record()
            time.sleep(state.get_delay)
            if self.path != f"/api/v1/executions/{_PROBE_ID}":
                self._answer(404, {"detail": "unknown"})
                return
            if state.cancelled:
                # A withdrawn start never had a phase (queued_start.py, #1650).
                ended = (
                    _detail("cancelled") if state.withdrawn else _detail("cancelled", "cancelled")
                )
                self._answer(200, ended)
                return
            body = state.details[min(state.gets, len(state.details) - 1)]
            state.gets += 1
            state.current = body
            if body is None:
                self._answer(404, {"detail": "Execution not found"})
            else:
                self._answer(200, body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/api/v1"
    finally:
        server.shutdown()


def _tail() -> str:
    lines = _SCRIPT.read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(_START)]
    assert len(starts) == 1, (
        f"could not find {_START!r} in {_SCRIPT.name}; this test no longer runs the probe"
    )
    return "\n".join(lines[starts[0] :])


def _definition(name: str) -> str:
    """A function from the script verbatim, one-line or block."""
    lines = _SCRIPT.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    if lines[start].rstrip().endswith("}"):
        return lines[start]
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _run(
    tmp: Path,
    api: str,
    *,
    skip_probe: bool = False,
    probe_timeout: int = _UNREACHED,
    cancel_timeout: int = _UNREACHED,
) -> subprocess.CompletedProcess[str]:
    preamble = f"""
set -euo pipefail
TAG=v0.40.0-beta.1; VERSION=0.40.0-beta.1; DRY=0; SKIP_PROBE={int(skip_probe)}
HOST=fake-host; API={api}; COMPOSE_DIR=/root/.syntropic137; COMPOSE=docker-compose.syntropic137.yaml
BAK=v0.39.0; TMP={tmp}; RECOVERY=""; T0=$(date +%s)
PROBE_WORKFLOW=telemetry-lag-probe-v1; PROBE_TIMEOUT={probe_timeout}; PROBE_CANCEL_TIMEOUT={cancel_timeout}
step() {{ printf '==> %s\\n' "$*"; }}
die() {{
    printf 'PIT STOP ABORTED: %s\\n' "$*" >&2
    if [ -n "$RECOVERY" ]; then printf '%s\\n' "$RECOVERY" >&2; fi
    exit 1
}}
sleep() {{ :; }}
{_definition("api_curl")}
{_definition("api")}
{_definition("maintenance")}
"""
    # The real curl behind a recorder of its argv: what `ps` would have shown (PC-85).
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    curl = shutil.which("curl")
    assert curl, "these tests drive the real curl"
    recorder = bin_dir / "curl"
    recorder.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {tmp}/curl_argv\nexec {curl} "$@"\n')
    recorder.chmod(0o755)
    return subprocess.run(
        ["bash", "-c", preamble + _tail(), str(_SCRIPT)],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "SYN_API_PASSWORD": _PASSWORD},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _calls(state: _Host) -> list[tuple[str, str]]:
    return [(method, path.removeprefix("/api/v1")) for method, path, _ in state.requests]


def _dispatched(state: _Host) -> bool:
    return ("POST", "/workflows/telemetry-lag-probe-v1/execute") in _calls(state)


def _cancel_requests(state: _Host) -> int:
    return _calls(state).count(("POST", f"/executions/{_PROBE_ID}/cancel"))


def _cancelled(state: _Host) -> bool:
    return _cancel_requests(state) > 0


def _admission_never_reclosed(state: _Host) -> bool:
    puts = [json.loads(body)["active"] for method, _, body in state.requests if method == "PUT"]
    return puts == [False]


def _failed_loudly(proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode != 0
    assert "PIT STOP DONE" not in proc.stdout + proc.stderr
    assert _PROBE_ID in proc.stderr
    assert "admission is OPEN" in proc.stderr
    assert "Nothing was rolled back" in proc.stderr
    assert (
        "cp docker-compose.syntropic137.yaml.bak-v0.39.0 docker-compose.syntropic137.yaml"
        in proc.stderr
    )


def _no_secret_leaked(proc: subprocess.CompletedProcess[str]) -> None:
    assert _PASSWORD not in proc.stdout + proc.stderr


_CLEANUP = 'curl -fsS -u "admin:$SYN_API_PASSWORD" -X POST {api}/executions/{id}/cancel'


def _verified_terminal_after_cancel(state: _Host) -> bool:
    """The last cancel was READ BACK: a GET of the probe came after it."""
    calls = _calls(state)
    cancel = ("POST", f"/executions/{_PROBE_ID}/cancel")
    last = max(i for i, call in enumerate(calls) if call == cancel)
    return ("GET", f"/executions/{_PROBE_ID}") in calls[last + 1 :]


def test_a_probe_that_reaches_running_is_cancelled_and_the_pit_stop_is_done(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    state.details = [
        None,
        _detail("running"),
        _detail("running", "pending"),
        _detail("running", "running"),
    ]
    proc = _run(tmp_path, api)
    assert proc.returncode == 0, proc.stderr
    assert "PIT STOP DONE: v0.40.0-beta.1 live in" in proc.stdout
    assert (
        f"Probe {_PROBE_ID} reached a running phase and was stopped (terminal, verified by GET)."
        in proc.stdout
    )
    assert "heartbeat=running" in proc.stdout
    # The probe went through the open gate, and was left terminal for the next drain.
    calls = _calls(state)
    assert calls.index(("PUT", "/maintenance")) < calls.index(
        ("POST", "/workflows/telemetry-lag-probe-v1/execute")
    )
    assert _cancelled(state)
    assert state.cancelled
    assert _verified_terminal_after_cancel(state)
    assert "status=cancelled phases=[heartbeat=cancelled]" in proc.stdout
    assert state.auths == {"Basic " + base64.b64encode(f"admin:{_PASSWORD}".encode()).decode()}
    _no_secret_leaked(proc)
    # The gate, the dispatch, the reads and the cancel: no command line carried it.
    argv = (tmp_path / "curl_argv").read_text()
    assert "-X PUT" in argv
    assert "-X POST" in argv
    assert _PASSWORD not in argv


def test_a_phase_that_already_completed_counts_as_started(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    state.details = [_detail("completed", "completed")]
    proc = _run(tmp_path, api)
    assert proc.returncode == 0, proc.stderr
    assert "PIT STOP DONE" in proc.stdout


def test_a_probe_queued_past_both_deadlines_is_withdrawn_verified_and_still_fails(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    """syn-api's shape for an accepted start waiting for capacity: ``queued``
    with no phases. Since #1650 the cancel withdraws it, and the pit stop reads
    the withdrawal back as ``cancelled`` before it exits. It still FAILS: the
    probe never ran, so nothing proved the start path."""
    state, api = host
    state.details = [_detail("queued")]
    # Whole seconds on a monotonic clock: a 1s deadline can pass before the
    # first read, and push CI on eda62183 failed with no status read at all.
    proc = _run(tmp_path, api, probe_timeout=3, cancel_timeout=3)
    _failed_loudly(proc)
    assert "did not reach a running phase within 3s" in proc.stderr
    assert "Last status: status=queued phases=[]" in proc.stderr
    assert state.withdrawn
    assert _verified_terminal_after_cancel(state)
    assert f"Probe {_PROBE_ID} is terminal, verified by GET: status=cancelled phases=[]" in (
        proc.stderr
    )
    assert "MAY STILL BE LIVE" not in proc.stderr
    assert _admission_never_reclosed(state)
    _no_secret_leaked(proc)


def test_a_deadline_passed_before_the_first_read_still_reports_the_probe(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    """On a slow host the probe's deadline can pass before its first read.
    main CI (0e2a9d996) hit it: ``PROBE_LAST: unbound variable`` killed the
    script under ``set -u`` instead of naming the probe."""
    state, api = host
    state.details = [_detail("queued")]
    proc = _run(tmp_path, api, probe_timeout=0, cancel_timeout=0)
    assert "unbound variable" not in proc.stderr
    _failed_loudly(proc)
    assert "no status read before the deadline" in proc.stderr
    _no_secret_leaked(proc)


@pytest.mark.parametrize(
    "probe",
    [[_detail("queued")], [_detail("running", "running")]],
    ids=["queued", "running"],
)
def test_a_cancel_accepted_but_never_terminal_fails_with_the_cleanup_command(
    tmp_path: Path, host: tuple[_Host, str], probe: list[dict[str, object] | None]
) -> None:
    """An accepted cancel is not proof. Whether the probe was still queued or
    already running, a cancel that answers 200 while GET never shows it
    terminal fails the pit stop, and names the exact command that stops it."""
    state, api = host
    state.details = probe
    state.cancel_lands = False
    # The cancel deadline is whole seconds on a monotonic clock: at 1s, a read
    # that crosses a second boundary leaves none for the cancel, and the
    # `running` case failed intermittently without one being sent.
    proc = _run(tmp_path, api, probe_timeout=1, cancel_timeout=3)
    assert proc.returncode != 0
    assert "PIT STOP DONE" not in proc.stdout + proc.stderr
    assert _cancelled(state)
    assert not state.cancelled
    assert f"PROBE {_PROBE_ID} MAY STILL BE LIVE" in proc.stderr
    assert _CLEANUP.format(api=api, id=_PROBE_ID) in proc.stderr
    assert "admission is OPEN" in proc.stderr
    assert _admission_never_reclosed(state)
    _no_secret_leaked(proc)


@pytest.mark.parametrize("ending", ["failed", "interrupted"])
def test_a_probe_that_fails_after_a_phase_ran_is_not_done(
    tmp_path: Path, host: tuple[_Host, str], ending: str
) -> None:
    """A phase was seen running, then the run FAILED rather than stopping:
    a failure is not the clean stop the pit stop asked for."""
    state, api = host
    state.details = [_detail("running", "running")]
    state.after_cancel = [_detail(ending, ending)]
    state.cancel_lands = False
    proc = _run(tmp_path, api)
    _failed_loudly(proc)
    assert f"probe {_PROBE_ID} FAILED after a phase ran" in proc.stderr
    assert f"Last status: status={ending} phases=[heartbeat={ending}]" in proc.stderr
    assert _admission_never_reclosed(state)


def test_slow_answers_cannot_stretch_the_probe_past_its_deadlines(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    """The bounds are wall-clock deadlines, and every request is capped to what
    is left of them: a GET that takes 20s may not hold a 2s probe for 20s."""
    state, api = host
    state.details = [_detail("queued")]
    state.get_delay = 20.0
    began = time.monotonic()
    proc = _run(tmp_path, api, probe_timeout=2, cancel_timeout=2)
    elapsed = time.monotonic() - began
    _failed_loudly(proc)
    # 2s + 2s of deadline, plus whole-second rounding and process start-up.
    assert elapsed < 10, f"took {elapsed:.1f}s against 4s of deadlines"


def test_a_start_dropped_before_it_existed_fails_without_done(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    """The #1641 shape: the dispatch answered 200 and the execution never existed."""
    state, api = host
    state.details = [None]
    state.cancel_lands = False
    proc = _run(tmp_path, api, probe_timeout=3, cancel_timeout=3)
    _failed_loudly(proc)
    assert "not found by GET" in proc.stderr
    assert f"PROBE {_PROBE_ID} MAY STILL BE LIVE" in proc.stderr
    assert _CLEANUP.format(api=api, id=_PROBE_ID) in proc.stderr


@pytest.mark.parametrize(
    "ending",
    [_detail("failed"), _detail("running", "failed"), _detail("cancelled"), _detail("interrupted")],
    ids=["run-failed", "phase-failed", "run-cancelled", "run-interrupted"],
)
def test_a_probe_that_ends_without_a_running_phase_fails_without_done(
    tmp_path: Path, host: tuple[_Host, str], ending: dict[str, object]
) -> None:
    state, api = host
    state.details = [_detail("running"), ending]
    proc = _run(tmp_path, api)
    _failed_loudly(proc)
    assert "ended without a phase reaching running" in proc.stderr
    assert f"status={ending['status']}" in proc.stderr
    assert _admission_never_reclosed(state)


def test_a_probe_that_cannot_be_dispatched_fails_without_done(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    state.dispatch_status = 404
    proc = _run(tmp_path, api)
    assert proc.returncode != 0
    assert "PIT STOP DONE" not in proc.stdout
    assert "syn workflow install workflows/probes/telemetry-lag" in proc.stderr
    assert "admission is OPEN" in proc.stderr
    _no_secret_leaked(proc)


def test_a_probe_whose_cancel_never_lands_is_not_done(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    """Started, but left in flight: the next pit stop's drain would wait on it."""
    state, api = host
    state.details = [_detail("running", "running")]
    state.cancel_lands = False
    proc = _run(tmp_path, api, cancel_timeout=3)
    assert proc.returncode != 0
    assert "PIT STOP DONE" not in proc.stdout
    assert f"the start path works, but probe {_PROBE_ID} is not terminal after 3s" in proc.stderr
    assert _CLEANUP.format(api=api, id=_PROBE_ID) in proc.stderr


def test_skip_probe_dispatches_nothing_and_says_so_loudly(
    tmp_path: Path, host: tuple[_Host, str]
) -> None:
    state, api = host
    proc = _run(tmp_path, api, skip_probe=True)
    assert proc.returncode == 0, proc.stderr
    assert not _dispatched(state)
    assert "--skip-probe: NO EXECUTION HAS BEEN SEEN TO START ON v0.40.0-beta.1" in proc.stderr
    assert "PROBE SKIPPED" in proc.stdout


def test_the_script_parses_skip_probe() -> None:
    """Through the real argument parser: an unknown flag stops at usage (2);
    --skip-probe is accepted and the run goes on to require the password."""
    env = {"PATH": os.environ["PATH"]}
    unknown = subprocess.run(
        ["bash", str(_SCRIPT), "0.40.0", "--no-such-flag"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert unknown.returncode == 2
    accepted = subprocess.run(
        ["bash", str(_SCRIPT), "0.40.0", "--skip-probe"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 1
    assert "SYN_API_PASSWORD must be set" in accepted.stderr
