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
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_FIXTURES = Path(__file__).parent / "fixtures" / "pit_stop"
_GOLDEN = _FIXTURES / "dry-run-all.txt"
_VERSION = "0.33.2-beta.9"

_SSH = """#!/usr/bin/env bash
echo "$*" >> "$PIT_LOG/ssh"
case "$*" in
    *"cat /root/.syntropic137/docker-compose.syntropic137.yaml"*) cat "$PIT_COMPOSE" ;;
esac
"""

# The drain reads /health and /executions; a dry run still makes both calls.
_CURL = """#!/usr/bin/env bash
echo "$*" >> "$PIT_LOG/curl"
out=""; url=""
while [ $# -gt 0 ]; do
    case "$1" in -o) out="$2"; shift 2 ;; http*) url="$1"; shift ;; *) shift ;; esac
done
case "$url" in
    */health) body='{"status": "healthy", "subscription": {"status": "healthy", "is_catching_up": false, "lag": 0}}' ;;
    */executions*) body='{"status_counts": {"completed": 3}}' ;;
    *) exit 22 ;;
esac
printf '%s' "$body" > "$out"
"""


def _dry_run(tmp: Path, *flags: str) -> tuple[str, str, Path]:
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
        "PIT_COMPOSE": str(_FIXTURES / "compose-tag.yaml"),
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
        assert not (log / "curl").exists(), "a gateway swap has no reason to read the API"

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
