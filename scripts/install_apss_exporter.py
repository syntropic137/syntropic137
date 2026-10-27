"""Install the pinned apss-session-exporter, verified, into the syn-api image.

Called by ``infra/docker/images/syn-api/Dockerfile`` in exec form, with no
shell, so no ``|| true`` or missing ``set -e`` can make a failed check pass.
Inputs come from the Dockerfile's build args, which BuildKit exposes to RUN as
environment variables:

- ``APSS_EXPORTER_VERSION``: exact release version, e.g. ``0.6.0``
- ``APSS_EXPORTER_SHA256_AMD64`` / ``APSS_EXPORTER_SHA256_ARM64``: sha256 of
  ``apss-session-exporter-linux-<arch>`` from the release's ``SHA256SUMS``

Order is the contract: download to a temp file beside the destination, verify
the sha256, run ``--version`` and require the pinned version, and only then
rename into place. Any failure exits non-zero and leaves nothing installed.

``APSS_EXPORTER_BASE_URL``, ``APSS_EXPORTER_ARCH`` and ``APSS_EXPORTER_DEST``
exist so the test can run this against a local file with no network
(scripts/tests/test_install_apss_exporter.py); the image build sets none of them.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

RELEASES = "https://github.com/AgentParadise/agentic-session-exporter/releases/download"
DEFAULT_DEST = Path("/usr/local/bin/apss-session-exporter")
MACHINE_TO_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


class InstallError(Exception):
    """Any reason the exporter must not be installed."""


@dataclass(frozen=True)
class Pin:
    version: str
    arch: str
    sha256: str
    url: str
    dest: Path


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise InstallError(f"{name} is not set")
    return value


def resolve_pin(env: Mapping[str, str]) -> Pin:
    version = _require(env, "APSS_EXPORTER_VERSION")
    machine = env.get("APSS_EXPORTER_ARCH") or platform.machine()
    arch = MACHINE_TO_ARCH.get(machine)
    if arch is None:
        raise InstallError(f"no pinned checksum for arch {machine!r}")
    sha256 = _require(env, f"APSS_EXPORTER_SHA256_{arch.upper()}").lower()
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise InstallError(f"APSS_EXPORTER_SHA256_{arch.upper()} is not a sha256 digest")
    base = env.get("APSS_EXPORTER_BASE_URL") or f"{RELEASES}/v{version}"
    dest = Path(env.get("APSS_EXPORTER_DEST") or DEFAULT_DEST)
    return Pin(version, arch, sha256, f"{base}/apss-session-exporter-linux-{arch}", dest)


def install(pin: Pin) -> None:
    pin.dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=pin.dest.parent, prefix=".apss-exporter-")
    tmp = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(pin.url, timeout=120) as resp:
            while chunk := resp.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        actual = digest.hexdigest()
        if actual != pin.sha256:
            raise InstallError(
                f"sha256 mismatch for {pin.url}: expected {pin.sha256}, got {actual}"
            )
        tmp.chmod(0o755)
        reported = subprocess.run(
            [str(tmp), "--version"], capture_output=True, text=True, timeout=30, check=False
        )
        words = reported.stdout.split()
        if reported.returncode != 0 or words[:2] != ["apss-session-exporter", pin.version]:
            raise InstallError(
                f"--version reported {reported.stdout.strip()!r} "
                f"(exit {reported.returncode}), expected {pin.version}"
            )
        tmp.replace(pin.dest)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    try:
        pin = resolve_pin(os.environ)
        install(pin)
    except (InstallError, OSError) as exc:
        print(f"apss-session-exporter: {exc}", file=sys.stderr)
        return 1
    print(f"apss-session-exporter {pin.version} ({pin.arch}) verified, installed at {pin.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
