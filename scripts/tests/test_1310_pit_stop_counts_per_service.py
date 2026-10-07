"""`--swap-only` prechecks each swapped service's pin and image by name (#1310).

The precheck used to count `syn-(api|gateway):$TAG` lines and images tagged
`$TAG` as one total, then compare it with how many services the pit stop swaps.
For `--service gateway` that total cannot tell the gateway from the API: with
only the API on the tag it counted 1 and recreated the gateway from its old pin
(verification of #1310). The same total held the two-image path together only
by coincidence.

These run the precheck block exactly as pit_stop.sh writes it, against a local
directory standing in for the host, a `remote` stub that runs each command with
bash instead of ssh, and a `docker images` stub that lists a chosen set.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_COMPOSE = "docker-compose.syntropic137.yaml"
_OLD, _NEW = "v0.33.1-beta.1", "v0.33.2-beta.1"
_REPO = "ghcr.io/syntropic137"

_DOCKER = """#!/usr/bin/env bash
[ "$1" = images ] && cat "$PIT_IMAGES"
"""


def _block(start: str, end: str) -> str:
    text = _SCRIPT.read_text()
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def _precheck(
    tmp: Path, service: str, api: str, gateway: str, images: list[str]
) -> subprocess.CompletedProcess[str]:
    """Run the precheck with the compose pinning api/gateway to the given tags."""
    host, bin_dir = tmp / "host", tmp / "bin"
    host.mkdir()
    bin_dir.mkdir()
    (host / _COMPOSE).write_text(
        f"services:\n  api:\n    image: {_REPO}/syn-api:{api}\n  gateway:\n    image: {_REPO}/syn-gateway:{gateway}\n"
    )
    (tmp / "images").write_text("".join(f"{line}\n" for line in images))
    docker = bin_dir / "docker"
    docker.write_text(_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    n, swapped = {"all": (2, "api gateway"), "gateway": (1, "gateway")}[service]
    preamble = f"""
set -euo pipefail
export PATH={bin_dir}:$PATH PIT_IMAGES={tmp / "images"}
TAG={_NEW}; MODE=swap; DRY=0; HOST=fake-host; N={n}; SWAPPED="{swapped}"
COMPOSE_DIR={host}; COMPOSE={_COMPOSE}
step() {{ printf '==> %s\\n' "$*"; }}
die() {{ printf 'PIT STOP ABORTED: %s\\n' "$*" >&2; exit 1; }}
remote() {{ bash -c "$*"; }}
"""
    text = _SCRIPT.read_text()
    begin = text.index("pins_on_tag() {")
    counters = text[begin : text.index("\n}\n", text.index("images_on_tag() {", begin)) + 3]
    precheck = _block('if [ "$MODE" = "swap" ] && [ "$DRY" = 0 ]; then', "\nfi\n") + "\nfi\n"
    return subprocess.run(
        ["bash", "-c", preamble + counters + precheck],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def _images(*services: str) -> list[str]:
    """What `docker images` lists: every named service on the new tag, plus noise
    that a tag-only count would have mistaken for one of them."""
    return [f"{_REPO}/syn-{svc}:{_NEW}" for svc in services] + [
        f"{_REPO}/syn-api:{_OLD}",
        f"{_REPO}/syn-gateway:{_OLD}",
        f"agentic-ws-claude:{_NEW}",
    ]


class TestGatewayOnly:
    def test_only_the_api_staged_is_refused(self, tmp_path: Path) -> None:
        proc = _precheck(tmp_path, "gateway", api=_NEW, gateway=_OLD, images=_images("api"))
        assert proc.returncode == 1
        assert "pins 0/1 services" in proc.stderr

    def test_api_image_alone_on_the_host_is_refused(self, tmp_path: Path) -> None:
        proc = _precheck(tmp_path, "gateway", api=_OLD, gateway=_NEW, images=_images("api"))
        assert proc.returncode == 1
        assert "0/1 images" in proc.stderr

    def test_the_gateway_staged_alone_passes(self, tmp_path: Path) -> None:
        proc = _precheck(tmp_path, "gateway", api=_OLD, gateway=_NEW, images=_images("gateway"))
        assert proc.returncode == 0, proc.stderr
        assert "pins=1 images=1" in proc.stdout

    def test_both_staged_passes(self, tmp_path: Path) -> None:
        proc = _precheck(
            tmp_path, "gateway", api=_NEW, gateway=_NEW, images=_images("api", "gateway")
        )
        assert proc.returncode == 0, proc.stderr
        assert "pins=1 images=1" in proc.stdout


class TestAll:
    def test_both_staged_passes(self, tmp_path: Path) -> None:
        proc = _precheck(tmp_path, "all", api=_NEW, gateway=_NEW, images=_images("api", "gateway"))
        assert proc.returncode == 0, proc.stderr
        assert "pins=2 images=2" in proc.stdout

    @pytest.mark.parametrize(("api", "gateway"), [(_NEW, _OLD), (_OLD, _NEW)])
    def test_one_pin_staged_is_refused(self, tmp_path: Path, api: str, gateway: str) -> None:
        proc = _precheck(
            tmp_path, "all", api=api, gateway=gateway, images=_images("api", "gateway")
        )
        assert proc.returncode == 1
        assert "pins 1/2 services" in proc.stderr

    @pytest.mark.parametrize("present", ["api", "gateway"])
    def test_one_image_on_the_host_is_refused(self, tmp_path: Path, present: str) -> None:
        proc = _precheck(tmp_path, "all", api=_NEW, gateway=_NEW, images=_images(present))
        assert proc.returncode == 1
        assert "1/2 images" in proc.stderr
