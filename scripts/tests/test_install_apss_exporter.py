"""Behaviour of scripts/install_apss_exporter.py, the syn-api image's exporter install.

Runs the real script as a subprocess, the way the Dockerfile does, against a
local stub "release" (a file:// base URL), so no network is touched. The
property that matters is fail-closed: every bad input exits non-zero and
leaves nothing at the destination, not even a temp file.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "install_apss_exporter.py"
VERSION = "0.6.0"
OTHER_SHA = "0" * 64


def _stub_release(root: Path, arch: str, reported_version: str = VERSION) -> str:
    """A release dir holding a fake exporter for ``arch``. Returns its sha256."""
    root.mkdir(parents=True, exist_ok=True)
    binary = root / f"apss-session-exporter-linux-{arch}"
    binary.write_text(
        f'#!/bin/sh\necho "apss-session-exporter {reported_version} (APS-V1-0004 SCS 1.0)"\n'
    )
    return hashlib.sha256(binary.read_bytes()).hexdigest()


def _run(release: Path, dest: Path, arch: str, **pins: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "APSS_EXPORTER_BASE_URL": release.as_uri(),
        "APSS_EXPORTER_DEST": str(dest),
        "APSS_EXPORTER_ARCH": arch,
        "APSS_EXPORTER_VERSION": VERSION,
        **pins,
    }
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )


def _assert_nothing_installed(dest: Path) -> None:
    assert not dest.exists()
    assert list(dest.parent.iterdir()) == [], "a partial or temp file was left behind"


@pytest.mark.unit
@pytest.mark.parametrize(("machine", "arch"), [("x86_64", "amd64"), ("aarch64", "arm64")])
def test_installs_the_verified_binary_for_each_arch(tmp_path: Path, machine: str, arch: str) -> None:
    release, dest = tmp_path / "release", tmp_path / "bin" / "apss-session-exporter"
    sha = _stub_release(release, arch)
    pins = {"APSS_EXPORTER_SHA256_AMD64": OTHER_SHA, "APSS_EXPORTER_SHA256_ARM64": OTHER_SHA}
    pins[f"APSS_EXPORTER_SHA256_{arch.upper()}"] = sha

    result = _run(release, dest, machine, **pins)

    assert result.returncode == 0, result.stderr
    assert dest.read_bytes() == (release / f"apss-session-exporter-linux-{arch}").read_bytes()
    assert os.access(dest, os.X_OK)
    assert [p.name for p in dest.parent.iterdir()] == [dest.name]


@pytest.mark.unit
def test_wrong_checksum_fails_and_installs_nothing(tmp_path: Path) -> None:
    release, dest = tmp_path / "release", tmp_path / "bin" / "apss-session-exporter"
    _stub_release(release, "arm64")

    result = _run(release, dest, "aarch64", APSS_EXPORTER_SHA256_ARM64=OTHER_SHA)

    assert result.returncode != 0
    assert "sha256 mismatch" in result.stderr
    _assert_nothing_installed(dest)


@pytest.mark.unit
def test_other_arch_checksum_is_not_accepted(tmp_path: Path) -> None:
    # The multi-arch pitfall: the amd64 digest must not verify the arm64 asset.
    release, dest = tmp_path / "release", tmp_path / "bin" / "apss-session-exporter"
    arm_sha = _stub_release(release, "arm64")

    result = _run(
        release,
        dest,
        "aarch64",
        APSS_EXPORTER_SHA256_AMD64=arm_sha,
        APSS_EXPORTER_SHA256_ARM64=OTHER_SHA,
    )

    assert result.returncode != 0
    _assert_nothing_installed(dest)


@pytest.mark.unit
def test_wrong_reported_version_fails_and_installs_nothing(tmp_path: Path) -> None:
    release, dest = tmp_path / "release", tmp_path / "bin" / "apss-session-exporter"
    sha = _stub_release(release, "arm64", reported_version="0.5.0")

    result = _run(release, dest, "aarch64", APSS_EXPORTER_SHA256_ARM64=sha)

    assert result.returncode != 0
    assert "expected 0.6.0" in result.stderr
    _assert_nothing_installed(dest)


@pytest.mark.unit
def test_unknown_arch_fails(tmp_path: Path) -> None:
    release, dest = tmp_path / "release", tmp_path / "bin" / "apss-session-exporter"
    sha = _stub_release(release, "arm64")

    result = _run(release, dest, "riscv64", APSS_EXPORTER_SHA256_ARM64=sha)

    assert result.returncode != 0
    assert not dest.exists()


@pytest.mark.unit
def test_missing_download_fails_and_installs_nothing(tmp_path: Path) -> None:
    release, dest = tmp_path / "release", tmp_path / "bin" / "apss-session-exporter"
    release.mkdir()

    result = _run(release, dest, "aarch64", APSS_EXPORTER_SHA256_ARM64=OTHER_SHA)

    assert result.returncode != 0
    _assert_nothing_installed(dest)


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["APSS_EXPORTER_VERSION", "APSS_EXPORTER_SHA256_ARM64"])
def test_missing_pin_fails(tmp_path: Path, missing: str) -> None:
    release, dest = tmp_path / "release", tmp_path / "bin" / "apss-session-exporter"
    sha = _stub_release(release, "arm64")
    pins = {"APSS_EXPORTER_SHA256_ARM64": sha, missing: ""}

    result = _run(release, dest, "aarch64", **pins)

    assert result.returncode != 0
    assert missing in result.stderr
    assert not dest.exists()
