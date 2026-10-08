"""A swap that leaves syn137-gateway `Created` must start it, verify it, and say so.

Twice on 2026-10-07/08 an API swap's `docker compose up` exited 0 and left
syn137-gateway `Created`: the dashboard was down ~4 minutes until someone ran
`docker start` by hand. The script used to notice only at verify, and abort.

These run the WHOLE script, `--swap-only --skip-probe`, against a stub host:
`ssh` runs each command locally, and a stateful `docker` stub whose
`compose up` leaves the gateway `Created`. Only `docker start` makes it
running again, so a script that does not start it cannot pass. `/health`
through the gateway fails while it is not running, as nginx would.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_VERSION = "0.34.0"
_START = "docker start syn137-gateway"

# HAZARD_UP: the state `compose up` leaves the gateway in, `created` being the
# incident. HAZARD_COMPOSE: how many `compose up` calls fail first with the dependency
# error (#1575). HAZARD_START: `ok` starts it, `fails` exits 1, `noop` exits 0
# and leaves it Created.
_DOCKER = r"""#!/usr/bin/env python3
import os, pathlib, sys
a = sys.argv[1:]
state = pathlib.Path(os.environ["HAZARD_STATE"])
with open(os.environ["HAZARD_CALLS"], "a") as f:
    f.write("docker " + " ".join(a) + "\n")
if a[0] == "images":
    print(f"ghcr.io/syntropic137/syn-api:v{os.environ['HAZARD_VERSION']}")
    print(f"ghcr.io/syntropic137/syn-gateway:v{os.environ['HAZARD_VERSION']}")
elif a[0] == "compose" and "up" in a:
    state.write_text(os.environ["HAZARD_UP"])
    print(" Container syn137-gateway  " + os.environ["HAZARD_UP"].capitalize())
    fails = pathlib.Path(os.environ["HAZARD_COMPOSE"])
    n = int(fails.read_text())
    if n > 0:
        fails.write_text(str(n - 1))
        print("dependency failed to start: container syn137-api is unhealthy")
        sys.exit(1)
elif a[:2] == ["start", "syn137-gateway"]:
    mode = os.environ["HAZARD_START"]
    if mode == "fails":
        print("Error response from daemon: cannot start syn137-gateway", file=sys.stderr)
        sys.exit(1)
    if mode == "ok":
        state.write_text("running")
    print("syn137-gateway")
elif a[:2] == ["image", "inspect"]:
    print("sha256:gateway" if "syn-gateway:" in a[2] else "sha256:api")
elif a[0] == "inspect":
    svc, fmt = a[1], a[-1]
    if ".Image" in fmt:
        print("sha256:gateway" if svc.endswith("gateway") else "sha256:api")
    elif ".State.Running" in fmt:
        print("true" if svc.endswith("api") or state.read_text() == "running" else "false")
    elif ".State.Status" in fmt:
        print("running 0 healthy")
    else:
        sys.exit(99)
elif a[0] == "exec":
    print("/usr/bin/docker")
else:
    sys.exit(99)
"""

_SSH = r"""#!/usr/bin/env python3
import os, subprocess, sys
sys.exit(subprocess.call(["bash", "-c", sys.argv[-1].replace("/root/.syntropic137", os.environ["HAZARD_HOST"])]))
"""

_CURL = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv[1:]
url = next(x for x in a if x.startswith("http"))
with open(os.environ["HAZARD_CALLS"], "a") as f:
    f.write("curl " + url + (" " + a[a.index("-d") + 1] if "-d" in a else "") + "\n")
if "/maintenance" in url:
    body = json.loads(a[a.index("-d") + 1]) if "-d" in a else {"active": False}
elif "/executions" in url:
    body = {"status_counts": {"completed": 1}, "executions": [], "total": 0}
elif "/version" in url:
    body = {"image_tag": "v" + os.environ["HAZARD_VERSION"], "commit": "synthetic"}
elif "/health" in url:
    if pathlib.Path(os.environ["HAZARD_STATE"]).read_text() != "running":
        sys.exit(7)  # nothing listening: the gateway is not running
    body = {"status": "healthy", "subscription": {"status": "healthy", "is_catching_up": False, "lag": 0}}
else:
    sys.exit(99)
if "-o" in a:
    pathlib.Path(a[a.index("-o") + 1]).write_text(json.dumps(body))
if "-w" in a:
    print("200", end="")
"""


@dataclass(frozen=True)
class Run:
    proc: subprocess.CompletedProcess[str]
    calls: list[str]
    state: str


def _pit_stop(
    tmp: Path,
    service: str,
    *,
    compose_fails: int = 0,
    start: str = "ok",
    up: str = "created",
    digest: str = "",
) -> Run:
    """`digest`, when given, qualifies the gateway pin: `...:<tag>@<digest>`."""
    host, bin_dir = tmp / "host", tmp / "bin"
    host.mkdir()
    bin_dir.mkdir()
    (tmp / "state").write_text("running")
    (tmp / "compose_fails").write_text(str(compose_fails))
    (host / "docker-compose.syntropic137.yaml").write_text(
        f"services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:v{_VERSION}\n"
        f"  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:v{_VERSION}{digest}\n"
    )
    for name, body in (("docker", _DOCKER), ("ssh", _SSH), ("curl", _CURL)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HAZARD_STATE": str(tmp / "state"),
        "HAZARD_CALLS": str(tmp / "calls"),
        "HAZARD_COMPOSE": str(tmp / "compose_fails"),
        "HAZARD_HOST": str(host),
        "HAZARD_START": start,
        "HAZARD_UP": up,
        "HAZARD_VERSION": _VERSION,
        "SYN_PIT_HOST": "fake-host",
        "SYN_PIT_API": "http://fake-host:8137/api/v1",
        "SYN_API_PASSWORD": "pw",
        # The #1575 wait polls every 15s; one poll is all the stub needs.
        "SYN_PIT_API_READY_TIMEOUT": "15",
    }
    proc = subprocess.run(
        [str(_SCRIPT), _VERSION, "--swap-only", "--skip-probe", "--service", service],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    calls = (tmp / "calls").read_text().splitlines() if (tmp / "calls").exists() else []
    return Run(proc, calls, (tmp / "state").read_text())


def _index(calls: list[str], needle: str) -> int:
    return next(i for i, c in enumerate(calls) if needle in c)


_CASES = [
    pytest.param("gateway", 0, id="gateway-compose-ok"),
    pytest.param("all", 0, id="all-compose-ok"),
    pytest.param("all", 1, id="all-compose-dependency-failure-then-retry"),
]


@pytest.mark.parametrize(("service", "compose_fails"), _CASES)
def test_a_gateway_left_created_is_started_verified_and_reported(
    tmp_path: Path, service: str, compose_fails: int
) -> None:
    run = _pit_stop(tmp_path, service, compose_fails=compose_fails)
    assert run.proc.returncode == 0, run.proc.stdout + run.proc.stderr
    assert run.state == "running"
    assert "PIT STOP DONE" in run.proc.stdout
    # Said so: the operator sees it was left Created and was started.
    assert (
        "syn137-gateway: running=false after compose up (left Created); starting it"
        in run.proc.stdout
    )
    assert "syn137-gateway: docker start issued" in run.proc.stdout
    assert "syn137-gateway: running=true image=sha256:gateway" in run.proc.stdout
    # Ordered: every compose up, then the start, then the running/image verify.
    assert run.calls.count(f"docker {_START.removeprefix('docker ')}") == 1
    start = _index(run.calls, _START)
    last_up = max(
        i for i, c in enumerate(run.calls) if c.startswith("docker compose") and " up " in c
    )
    verify = _index(run.calls, "docker inspect syn137-gateway --format {{.Image}}")
    assert last_up < start < verify
    assert len([c for c in run.calls if c.startswith("docker compose")]) == 1 + compose_fails
    # Routing works through the started gateway.
    assert any(c.endswith("/health") for c in run.calls[start:])


def test_the_gateway_alone_still_never_touches_the_api_or_admission(tmp_path: Path) -> None:
    run = _pit_stop(tmp_path, "gateway")
    assert run.proc.returncode == 0, run.proc.stderr
    (up,) = [c for c in run.calls if c.startswith("docker compose")]
    assert up.endswith("up -d --no-deps gateway")
    assert not [
        c for c in run.calls if "/maintenance" in c or "/executions" in c or "/version" in c
    ]
    assert not [c for c in run.calls if "syn137-api" in c or "syn-api:" in c]


@pytest.mark.parametrize("service", ["gateway", "all"])
def test_a_gateway_that_compose_started_is_not_started_again(tmp_path: Path, service: str) -> None:
    """Compose did its job: nothing to start, and the operator is told so."""
    run = _pit_stop(tmp_path, service, up="running")
    assert run.proc.returncode == 0, run.proc.stderr
    assert "syn137-gateway: running after compose up" in run.proc.stdout
    assert not [c for c in run.calls if _START in c]


@pytest.mark.parametrize("service", ["gateway", "all"])
@pytest.mark.parametrize(
    ("start", "message"),
    [
        ("fails", "docker start syn137-gateway failed on fake-host"),
        ("noop", "syn137-gateway is not running after the swap"),
    ],
)
def test_a_gateway_that_will_not_start_aborts_with_the_recovery(
    tmp_path: Path, service: str, start: str, message: str
) -> None:
    run = _pit_stop(tmp_path, service, start=start)
    assert run.proc.returncode == 1
    assert run.state == "created"
    assert "PIT STOP DONE" not in run.proc.stdout
    assert f"PIT STOP ABORTED: {message}" in run.proc.stderr
    assert "RECOVERY:" in run.proc.stderr
    if service == "gateway":
        assert "admission was never paused" in run.proc.stderr
    else:
        assert "admission is still PAUSED" in run.proc.stderr
        # Never resumed over a gateway that is down.
        assert [c for c in run.calls if '"active": true' in c]
        assert not [c for c in run.calls if '"active": false' in c]


@pytest.mark.parametrize("service", ["gateway", "all"])
def test_a_target_tag_qualified_by_an_old_digest_is_refused_before_any_swap(
    tmp_path: Path, service: str
) -> None:
    """Docker runs `<tag>@<digest>` by its digest: the target tag in front of
    an old digest, with the target image loaded, would recreate the gateway
    from the OLD bytes. The precheck must stop it before compose runs."""
    run = _pit_stop(tmp_path, service, up="running", digest="@sha256:" + "0" * 64)
    assert run.proc.returncode == 1
    pins = {"gateway": "0/1", "all": "1/2"}[service]
    assert f"pins {pins} services to v{_VERSION}; stage it first" in run.proc.stderr
    assert not [c for c in run.calls if c.startswith("docker compose")]
    assert not [c for c in run.calls if '"active": true' in c]
