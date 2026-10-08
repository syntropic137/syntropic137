"""`--service gateway` swaps the gateway alone, with no gate and no drain (#1310, 0.1).

The gateway is on `syn-internal` only, never `agent-net`, so no execution can
depend on it: recreating it needs neither the admission gate nor the drain that
an API swap does. Every stage of a pit stop assumed two images, so each one is
pinned here for the one-image path.

These run the WHOLE script with `--dry-run`, as an operator would, with `ssh`
and `curl` on PATH standing in for the host and the API. The default path is
held to the dry-run output the two-image script printed before the flag
existed (`fixtures/pit_stop/dry-run-all.txt`), so adding the flag can be shown
not to have moved it.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_FIXTURES = Path(__file__).parent / "fixtures" / "pit_stop"
_GOLDEN = _FIXTURES / "dry-run-all.txt"
#: The same, on a host whose compose already pins both services to the target:
#: a replayed stage, which the original script answered with its own message.
_GOLDEN_STAGED = _FIXTURES / "dry-run-all-staged.txt"
#: A version no real pit stop ever ships. The script refuses to run when
#: <repo>_worktrees/pit-stop-<version> exists, and on the maintainer's machine
#: every real beta leaves one behind, so a real-looking version failed this
#: whole file locally (0.33.2-beta.9 did).
_VERSION = "0.0.0-beta.1310"

_SSH = """#!/usr/bin/env bash
echo "$*" >> "$PIT_LOG/ssh"
case "$*" in
    *"cat /root/.syntropic137/docker-compose.syntropic137.yaml"*) cat "$PIT_COMPOSE" ;;
esac
"""

# The prechecks read /workflows (the probe's) and /health (the disk), and the
# drain reads /health and /executions; a dry run still makes every one of them.
_CURL = """#!/usr/bin/env bash
echo "$*" >> "$PIT_LOG/curl"
out=""; url=""
while [ $# -gt 0 ]; do
    case "$1" in -o) out="$2"; shift 2 ;; http*) url="$1"; shift ;; *) shift ;; esac
done
case "$url" in
    */health) body='{"status": "healthy", "subscription": {"status": "healthy", "is_catching_up": false, "lag": 0}}' ;;
    */executions*) body='{"status_counts": {"completed": 3}}' ;;
    */workflows*) body='{"workflows": [{"id": "telemetry-lag-probe-v1", "is_archived": false}]}' ;;
    *) exit 22 ;;
esac
printf '%s' "$body" > "$out"
"""


def _dry_run(tmp: Path, *flags: str, compose: str = "compose-tag.yaml") -> tuple[str, str, Path]:
    """A dry run's normalised stdout, its stderr, and where the stubs logged."""
    bin_dir, log = tmp / "bin", tmp / "log"
    bin_dir.mkdir()
    log.mkdir()
    for name, body in (("ssh", _SSH), ("curl", _CURL)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PIT_LOG": str(log),
        "PIT_COMPOSE": str(_FIXTURES / compose),
        "SYN_API_PASSWORD": "pw",
        "SYN_PIT_HOST": "root@fake-host",
        "SYN_PIT_API": "http://fake-host:8137/api/v1",
    }
    proc = subprocess.run(
        [str(_SCRIPT), _VERSION, "--dry-run", *flags],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    common = subprocess.run(
        ["git", "-C", str(_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    repo_top = str(Path(common).parent) if Path(common).name == ".git" else common
    out = re.sub(r"\[\d\d:\d\d:\d\dZ \+\d+s\]", "[T]", proc.stdout)
    return out.replace(str(Path(repo_top).parent), "<PARENT>"), proc.stderr, log


def _lines(out: str, needle: str) -> list[str]:
    return [line for line in out.splitlines() if needle in line]


class TestTheDefaultIsUnchanged:
    def test_dry_run_output_is_what_the_two_image_script_printed(self, tmp_path: Path) -> None:
        out, _, _ = _dry_run(tmp_path)
        assert out == _GOLDEN.read_text()

    def test_service_all_is_the_default(self, tmp_path: Path) -> None:
        out, _, _ = _dry_run(tmp_path, "--service", "all")
        assert out == _GOLDEN.read_text()

    @pytest.mark.parametrize("flags", [(), ("--service", "all")])
    def test_an_already_staged_host_prints_what_the_two_image_script_printed(
        self, tmp_path: Path, flags: tuple[str, ...]
    ) -> None:
        out, _, _ = _dry_run(tmp_path, *flags, compose="compose-staged.yaml")
        assert out == _GOLDEN_STAGED.read_text()


class TestGatewayOnly:
    def test_builds_one_image(self, tmp_path: Path) -> None:
        out, _, _ = _dry_run(tmp_path, "--service", "gateway")
        (build,) = _lines(out, "docker buildx build")
        assert "syn-gateway" in build and "syn-api" not in build

    def test_ships_one_image(self, tmp_path: Path) -> None:
        out, _, _ = _dry_run(tmp_path, "--service", "gateway")
        (save,) = _lines(out, "(dry-run) docker save")
        assert save.split("docker save ", 1)[1].split(" | ")[0] == (
            f"ghcr.io/syntropic137/syn-gateway:v{_VERSION}"
        )

    def test_repoints_only_the_gateway(self, tmp_path: Path) -> None:
        """What the repoint reports is what it changed: one pin, the gateway's."""
        out, err, _ = _dry_run(tmp_path, "--service", "gateway")
        assert _lines(err, "syn-gateway: ") == [
            "   syn-gateway: ghcr.io/syntropic137/syn-gateway:v0.33.1-beta.2"
            f" -> ghcr.io/syntropic137/syn-gateway:v{_VERSION}"
        ]
        assert _lines(err, "syn-api: ") == []
        (write,) = _lines(out, "sha256sum -c")
        assert "docker-compose.syntropic137.yaml.bak-v0.33.1-beta.2" in write

    def test_never_touches_admission_or_waits_for_a_drain(self, tmp_path: Path) -> None:
        out, _, log = _dry_run(tmp_path, "--service", "gateway")
        assert "/maintenance" not in out
        assert "drain:" not in out
        reads = (log / "curl").read_text().splitlines()
        # The disk report is the one read left: it is a report, not a gate,
        # and it is just as true before loading one image as two.
        assert reads and all(
            r.split("http://fake-host:8137/api/v1", 1)[1].startswith("/health ") for r in reads
        ), reads

    def test_dispatches_no_probe_and_never_checks_for_one(self, tmp_path: Path) -> None:
        """The probe proves a run can START, which a gateway swap does not touch;
        it also waits minutes and spends tokens, so a gateway pit stop skips it,
        and its precheck with it (#1310)."""
        out, _, log = _dry_run(tmp_path, "--service", "gateway")
        assert "probe" not in out
        assert "/workflows" not in (log / "curl").read_text()

    def test_recreates_the_gateway_without_its_dependencies(self, tmp_path: Path) -> None:
        out, _, _ = _dry_run(tmp_path, "--service", "gateway")
        (up,) = _lines(out, "docker compose")
        assert up.rstrip().endswith("up -d --no-deps gateway")
        assert "DRY RUN DONE" in out

    def test_an_unknown_service_is_refused(self, tmp_path: Path) -> None:
        proc = subprocess.run(
            [str(_SCRIPT), _VERSION, "--dry-run", "--service", "api"],
            env={**os.environ, "SYN_API_PASSWORD": "pw"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0
        assert "--service" in proc.stderr


_BRANCH = 'if [ "$SERVICE" = gateway ]; then'


def _gateway_branch() -> str:
    """The gateway-only swap and verify, verbatim, from its `if` to its `fi`."""
    lines = _SCRIPT.read_text().splitlines()
    (start,) = [i for i, line in enumerate(lines) if line == _BRANCH]
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start : end + 1])


def _function(name: str) -> str:
    lines = _SCRIPT.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


@contextmanager
def _api(statuses: list[int], log: Path) -> Iterator[str]:
    """A real HTTP server answering each request with the next status (the last
    repeats), logging `api <path>` per request. Yields the API base URL."""
    remaining = list(statuses)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            with log.open("a") as f:
                f.write(f"api {self.path.removeprefix('/api/v1')}\n")
            code = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            body = b'{"status": "healthy"}' if code == 200 else b""
            self.send_response(code)
            if code == 302:
                self.send_header("Location", "/login")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/api/v1"
    finally:
        server.shutdown()
        server.server_close()


def _run_branch(
    tmp: Path,
    *,
    running_image: str = "sha256:new",
    running: str = "true",
    health: list[int] | None = None,
    ssh_down: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the branch for real (DRY=0) with `remote` playing the host, and the
    script's own `api_curl` and the real curl asking a real HTTP server that
    answers /health with `health`, in order. Every remote and api call is
    logged, in order."""
    log = tmp / "calls"
    with _api(health or [200], log) as api_url:
        return _run_branch_against(tmp, log, api_url, running_image, running, ssh_down)


def _run_branch_against(
    tmp: Path, log: Path, api_url: str, running_image: str, running: str, ssh_down: bool
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    preamble = f"""
set -euo pipefail
TAG=v0.0.0-beta.1310; SERVICE=gateway; DRY=0; HOST=fake-host; API={api_url}; SYN_API_PASSWORD=pw
COMPOSE_DIR=/root/.syntropic137; COMPOSE=docker-compose.syntropic137.yaml; TMP={tmp}
RECOVERY=""; T0=$(date +%s)
step() {{ printf '==> %s\\n' "$*"; }}
die() {{
    printf 'PIT STOP ABORTED: %s\\n' "$*" >&2
    if [ -n "$RECOVERY" ]; then printf '%s\\n' "$RECOVERY" >&2; fi
    exit 1
}}
run() {{ "$@"; }}
sleep() {{ :; }}
remote() {{
    echo "remote $*" >> {log}
    if [ {int(ssh_down)} = 1 ]; then echo "ssh: connect timed out" >&2; return 255; fi
    case "$*" in
        *"docker compose"*) echo " Container syn137-gateway  Started" ;;
        *"docker image inspect ghcr.io/syntropic137/syn-gateway:"*) echo sha256:new ;;
        *"docker inspect syn137-gateway --format '{{{{.Image}}}}'"*) echo {running_image} ;;
        *"docker inspect syn137-gateway --format '{{{{.State.Running}}}}'"*) echo {running} ;;
        *"docker start syn137-gateway"*) echo syn137-gateway ;;
        *) echo "unexpected remote: $*" >&2; return 99 ;;
    esac
}}
{_function("api_curl")}
maintenance() {{ echo "maintenance $1" >> {log}; }}
{_function("start_gateway")}
{_function("swapped_is_running")}
"""
    proc = subprocess.run(
        ["bash", "-c", preamble + _gateway_branch()],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return proc, log.read_text().splitlines() if log.exists() else []


class TestGatewayOnlyLive:
    def test_swaps_and_verifies_without_touching_the_api_or_admission(self, tmp_path: Path) -> None:
        proc, calls = _run_branch(tmp_path, health=[502, 503, 200])
        assert proc.returncode == 0, proc.stderr
        assert "PIT STOP DONE: syn-gateway v0.0.0-beta.1310" in proc.stdout
        compose = [c for c in calls if "docker compose" in c]
        assert compose == [
            "remote cd /root/.syntropic137 && docker compose -f "
            "docker-compose.syntropic137.yaml up -d --no-deps gateway"
        ]
        assert not [c for c in calls if "syn137-api" in c or "syn-api" in c]
        assert not [c for c in calls if c.startswith("maintenance")]
        # /health, retried until the new gateway routes; never /version.
        assert [c for c in calls if c.startswith("api ")] == ["api /health"] * 3

    def test_a_gateway_on_the_old_image_fails_verify(self, tmp_path: Path) -> None:
        proc, _ = _run_branch(tmp_path, running_image="sha256:old")
        assert proc.returncode != 0
        assert "syn137-gateway is not running the image tagged" in proc.stderr
        assert "admission was never paused" in proc.stderr

    def test_a_gateway_that_is_not_running_fails_verify(self, tmp_path: Path) -> None:
        proc, _ = _run_branch(tmp_path, running="false")
        assert proc.returncode != 0
        assert "syn137-gateway is not running after the swap" in proc.stderr

    def test_health_that_never_answers_fails_verify(self, tmp_path: Path) -> None:
        proc, _ = _run_branch(tmp_path, health=[502])
        assert proc.returncode != 0
        assert "did not answer 200 through the new gateway" in proc.stderr

    @pytest.mark.parametrize("status", [204, 302])
    def test_a_success_that_is_not_200_never_completes(self, tmp_path: Path, status: int) -> None:
        """curl -f passes a 204 and a 302; neither is /health routed to the API."""
        proc, calls = _run_branch(tmp_path, health=[status])
        assert proc.returncode != 0
        assert f"did not answer 200 through the new gateway (last status: {status})" in proc.stderr
        assert "PIT STOP DONE" not in proc.stdout
        assert ": 200" not in proc.stdout
        assert [c for c in calls if c.startswith("api ")] == ["api /health"] * 10

    @pytest.mark.parametrize("status", [204, 302])
    def test_a_non_200_success_then_a_200_completes(self, tmp_path: Path, status: int) -> None:
        proc, _ = _run_branch(tmp_path, health=[status, 200])
        assert proc.returncode == 0, proc.stderr
        assert "GET /health through syn137-gateway: 200" in proc.stdout

    def test_losing_the_host_aborts_through_die_with_the_recovery(self, tmp_path: Path) -> None:
        proc, _ = _run_branch(tmp_path, ssh_down=True)
        assert proc.returncode != 0
        assert "PIT STOP ABORTED" in proc.stderr
        assert "up -d --no-deps gateway" in proc.stderr
