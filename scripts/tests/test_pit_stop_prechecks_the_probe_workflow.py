"""The pit stop refuses an unusable probe workflow BEFORE it touches anything (PC-87),
and never puts the API password on a command line (PC-85).

PC-87: beta.11 built, shipped, gated, drained for 40 minutes, swapped and
verified, and only then found its probe workflow archived: "Workflow
telemetry-lag-probe-v1 is archived and cannot launch executions".

PC-85: `curl -u "admin:$SYN_API_PASSWORD"` put the password in curl's argv,
where any user on the operator's machine reads it through `ps`.

These run the WHOLE script, from its argument parser, against a fake API served
over real HTTP. Every tool a later stage would use - docker, ssh, just, and git
past the one read that locates the repository - is a recorder on PATH that
refuses, so "nothing was built or gated" is observed, not inferred. curl is the
real curl behind a recorder that logs its argv.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
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
_PROBE = "telemetry-lag-probe-v1"
# Quote, backslash and dollar: what a curl config line and a shell both mangle.
_PASSWORD = 's3cret"pit\\pw$x'
_INSTALL = "syn workflow install workflows/probes/telemetry-lag"


def _summary(workflow_id: str, *, archived: bool) -> dict[str, object]:
    return {
        "id": workflow_id,
        "name": "Probe",
        "workflow_type": "custom",
        "classification": "standard",
        "phase_count": 1,
        "is_archived": archived,
        "requires_repos": False,
        "tags": [],
    }


@dataclass
class _Api:
    """``workflows`` is what GET /workflows answers, before ``search``
    filters it the way syn-api does (substring of id or name)."""

    workflows: list[dict[str, object]] = field(default_factory=list)
    list_status: int = 200
    requests: list[tuple[str, str]] = field(default_factory=list)
    auths: set[str] = field(default_factory=set)


@pytest.fixture
def fake_api() -> Iterator[tuple[_Api, str]]:
    state = _Api()

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, code: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self) -> None:
            state.auths.add(self.headers.get("Authorization", ""))
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            state.requests.append((self.command, self.path))

        def do_GET(self) -> None:
            self._record()
            url = urlsplit(self.path)
            if url.path == "/api/v1/workflows":
                if state.list_status != 200:
                    self._answer(state.list_status, {"detail": "nope"})
                    return
                query = parse_qs(url.query)
                search = query.get("search", [""])[0].lower()
                archived_too = query.get("include_archived", ["false"])[0] == "true"
                rows = [
                    w
                    for w in state.workflows
                    if search in str(w["id"]).lower() and (archived_too or not w["is_archived"])
                ]
                self._answer(200, {"workflows": rows, "total": len(rows)})
            elif url.path == "/api/v1/health":
                self._answer(200, {"status": "healthy"})
            else:
                self._answer(404, {"detail": "unknown"})

        def do_PUT(self) -> None:
            self._record()
            self._answer(500, {"detail": "the gate must not be touched by these runs"})

        def do_POST(self) -> None:
            self._record()
            self._answer(500, {"detail": "nothing may be dispatched by these runs"})

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/api/v1"
    finally:
        server.shutdown()


@dataclass
class _Run:
    proc: subprocess.CompletedProcess[str]
    curl_argv: str
    touched: list[str]


def _run(tmp: Path, api: str, *flags: str, password: str = _PASSWORD) -> _Run:
    """The real script, end to end. ``touched`` lists every docker, ssh, just
    or git (other than locating the repository) the script tried to run."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    curl = shutil.which("curl")
    assert curl, "these tests drive the real curl"
    (bin_dir / "curl").write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> {tmp}/curl_argv\nexec {curl} "$@"\n'
    )
    refuse = f'#!/bin/sh\necho "$(basename "$0") $*" >> {tmp}/touched\nexit 1\n'
    for tool in ("docker", "ssh", "just"):
        (bin_dir / tool).write_text(refuse)
    # The repository is a fake one in tmp, so no path can fetch or add a worktree for real.
    (bin_dir / "git").write_text(
        f'#!/bin/sh\ncase "$*" in *--git-common-dir*) echo {tmp}/repo/.git; exit 0 ;; esac\n'
        + refuse.removeprefix("#!/bin/sh\n")
    )
    for script in bin_dir.iterdir():
        script.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(_SCRIPT), "0.40.0-beta.1", *flags],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SYN_API_PASSWORD": password,
            "SYN_PIT_API": api,
            "SYN_PIT_HOST": "fake-host",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    argv = tmp / "curl_argv"
    touched = tmp / "touched"
    return _Run(
        proc,
        argv.read_text() if argv.exists() else "",
        touched.read_text().splitlines() if touched.exists() else [],
    )


def _refused_before_anything(run: _Run, state: _Api) -> None:
    """Died on the precheck: no build, no ship, no git, no gate, no dispatch."""
    assert run.proc.returncode == 1, run.proc.stdout + run.proc.stderr
    assert "PIT STOP ABORTED" in run.proc.stderr
    assert "Nothing was built or gated" in run.proc.stderr
    assert run.touched == []
    assert all(method == "GET" for method, _ in state.requests), state.requests
    assert "prepare:" not in run.proc.stdout


def _password_stayed_secret(run: _Run, state: _Api) -> None:
    assert run.curl_argv, "the recorder saw no curl at all, so it proved nothing"
    assert _PASSWORD not in run.curl_argv
    assert "admin:" not in run.curl_argv
    assert _PASSWORD not in run.proc.stdout + run.proc.stderr
    # ...and it still arrived, intact, as the credential.
    assert state.auths == {"Basic " + base64.b64encode(f"admin:{_PASSWORD}".encode()).decode()}


# Both modes that dispatch the probe. --swap-only is the one that gates and
# drains production after an earlier --stage-only, so it must refuse first too.
_PROBING_MODES = pytest.mark.parametrize("flags", [(), ("--swap-only",)], ids=["all", "swap-only"])


@_PROBING_MODES
def test_an_archived_probe_workflow_stops_the_pit_stop_before_anything(
    tmp_path: Path, fake_api: tuple[_Api, str], flags: tuple[str, ...]
) -> None:
    state, api = fake_api
    state.workflows = [_summary(_PROBE, archived=True)]
    run = _run(tmp_path, api, *flags)
    _refused_before_anything(run, state)
    assert f"the probe workflow {_PROBE} is archived on {api}" in run.proc.stderr
    assert _INSTALL in run.proc.stderr
    assert "--skip-probe" in run.proc.stderr
    # The install command is printed with the password as a LITERAL for the operator's shell.
    assert "SYN_API_PASSWORD=$SYN_API_PASSWORD" in run.proc.stderr
    _password_stayed_secret(run, state)


@_PROBING_MODES
def test_a_missing_probe_workflow_stops_the_pit_stop_before_anything(
    tmp_path: Path, fake_api: tuple[_Api, str], flags: tuple[str, ...]
) -> None:
    """``search`` is a substring match, so an active workflow whose id merely
    CONTAINS the probe's is not the probe."""
    state, api = fake_api
    state.workflows = [_summary(f"{_PROBE}0", archived=False)]
    run = _run(tmp_path, api, *flags)
    _refused_before_anything(run, state)
    assert f"the probe workflow {_PROBE} is missing on {api}" in run.proc.stderr
    assert _INSTALL in run.proc.stderr
    assert "--skip-probe" in run.proc.stderr


def test_an_unreadable_workflow_list_stops_the_pit_stop_before_anything(
    tmp_path: Path, fake_api: tuple[_Api, str]
) -> None:
    state, api = fake_api
    state.list_status = 500
    run = _run(tmp_path, api)
    _refused_before_anything(run, state)
    assert f"could not read the probe workflow {_PROBE}" in run.proc.stderr


def test_an_active_probe_workflow_lets_the_pit_stop_go_on(
    tmp_path: Path, fake_api: tuple[_Api, str]
) -> None:
    """Dry run: the precheck passes and the stages after it start. The fake
    ssh then refuses to read the compose file, which is where this one ends."""
    state, api = fake_api
    state.workflows = [_summary(f"{_PROBE}0", archived=True), _summary(_PROBE, archived=False)]
    run = _run(tmp_path, api, "--dry-run")
    assert f"probe workflow {_PROBE}: active" in run.proc.stdout
    assert "prepare:" in run.proc.stdout
    assert "could not read the deployed compose file" in run.proc.stderr
    assert "probe workflow" not in run.proc.stderr
    assert all(method == "GET" for method, _ in state.requests)
    _password_stayed_secret(run, state)


@pytest.mark.parametrize("brk", ["\n", "\r"], ids=["lf", "cr"])
def test_a_password_with_a_line_break_is_refused_without_reaching_any_output(
    tmp_path: Path, fake_api: tuple[_Api, str], brk: str
) -> None:
    """A line break would end curl's config line, and curl echoes the rest of
    that line in its parse error: the tail of the password reached stderr
    (found in review of #1656, reproduced with a synthetic password)."""
    state, api = fake_api
    state.workflows = [_summary(_PROBE, archived=False)]
    run = _run(tmp_path, api, "--dry-run", password=f"head-part{brk}visible-secret-tail")
    assert run.proc.returncode == 1
    assert "contains a line break" in run.proc.stderr
    out = run.proc.stdout + run.proc.stderr
    assert "visible-secret-tail" not in out
    assert "head-part" not in out
    assert state.requests == []


@pytest.mark.parametrize("flag", ["--skip-probe", "--stage-only"])
def test_a_run_that_dispatches_no_probe_does_not_check_for_one(
    tmp_path: Path, fake_api: tuple[_Api, str], flag: str
) -> None:
    state, api = fake_api
    state.workflows = [_summary(_PROBE, archived=True)]
    run = _run(tmp_path, api, "--dry-run", flag)
    assert "prepare:" in run.proc.stdout
    assert not any(path.startswith("/api/v1/workflows") for _, path in state.requests)
