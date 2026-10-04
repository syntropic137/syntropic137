"""`pit-stop --stage-only` must stage on a host installed from a release.

A release compose pins syn-api and syn-gateway BY DIGEST, each to its own, and
the stage step used to read only `syn-api:vX`: it aborted with "could not read
the syn-api pin" on every release-installed host (v0.33.2-beta.1, 2026-10-03).
A hotfixed host carries a different tag per service with no registry prefix
(#1431), which a single sed for both services could not repoint either.

These drive the helper through the CLI pit_stop.sh calls, and check its output
with the exact count `--swap-only` prechecks, read out of the script: a stage
that writes something the swap then refuses is the same abort one step later.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_HELPER = _ROOT / "scripts" / "pit_stop_repoint.py"
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_FIXTURES = Path(__file__).parent / "fixtures" / "pit_stop"
_TAG = "v0.33.2-beta.1"


def _stage(
    fixture: str, tmp_path: Path, tag: str = _TAG
) -> tuple[subprocess.CompletedProcess[str], Path]:
    staged = tmp_path / "staged.yaml"
    proc = subprocess.run(
        [sys.executable, str(_HELPER), tag, str(_FIXTURES / fixture), str(staged)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, staged


def _precheck_count(compose: Path, tag: str = _TAG) -> int:
    """Run the `--swap-only` precheck's own grep, as written in pit_stop.sh."""
    (pattern,) = re.findall(r"pins=\"\$\(remote \"grep -c '([^']+)' ", _SCRIPT.read_text())
    proc = subprocess.run(
        ["grep", "-c", pattern.replace("$TAG", tag), str(compose)],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(proc.stdout)


def _image_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if "image:" in line]


class TestStagesEveryPinForm:
    @pytest.mark.parametrize(
        ("fixture", "backup"),
        [
            ("compose-digest.yaml", "sha256-bf783882d031"),
            ("compose-tag.yaml", "v0.33.1-beta.2"),
            ("compose-hotfixed.yaml", "v0.30.0-beta.7-hotfix1046b"),
        ],
    )
    def test_both_services_end_on_the_shipped_ref_and_pass_the_swap_precheck(
        self, fixture: str, backup: str, tmp_path: Path
    ) -> None:
        proc, staged = _stage(fixture, tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == backup
        assert f"image: ghcr.io/syntropic137/syn-api:{_TAG}" in staged.read_text()
        assert f"ghcr.io/syntropic137/syn-gateway:{_TAG}" in staged.read_text()
        assert _precheck_count(staged) == 2

    def test_only_the_two_pins_change(self, tmp_path: Path) -> None:
        """Every other line, including the other digest-pinned images, is byte-identical."""
        _, staged = _stage("compose-digest.yaml", tmp_path)

        before = (_FIXTURES / "compose-digest.yaml").read_text().splitlines()
        after = staged.read_text().splitlines()
        changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
        assert [b.strip() for _, b in changed] == [
            f"image: ghcr.io/syntropic137/syn-api:{_TAG}",
            f"image: ghcr.io/syntropic137/syn-gateway:{_TAG}",
        ]

    def test_the_backup_name_is_filesystem_safe(self, tmp_path: Path) -> None:
        proc, _ = _stage("compose-digest.yaml", tmp_path)

        assert re.fullmatch(r"[0-9A-Za-z._-]+", proc.stdout.strip())


class TestNothingToStage:
    def test_an_already_staged_file_asks_for_no_backup(self, tmp_path: Path) -> None:
        first, staged = _stage("compose-digest.yaml", tmp_path)
        assert first.returncode == 0
        again = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(staged), str(tmp_path / "again.yaml")],
            capture_output=True,
            text=True,
            check=False,
        )

        assert again.returncode == 0, again.stderr
        assert again.stdout.strip() == ""
        assert (tmp_path / "again.yaml").read_text() == staged.read_text()


class TestRefusesToGuess:
    @pytest.mark.parametrize(
        ("compose", "reason"),
        [
            (
                "services:\n  api:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "exactly one syn-api",
            ),
            (
                "services:\n  a:\n    image: ghcr.io/syntropic137/syn-api:v1\n"
                "  b:\n    image: ghcr.io/syntropic137/syn-api:v2\n"
                "  g:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "exactly one syn-api",
            ),
            (
                "services:\n  a:\n    image: ghcr.io/syntropic137/syn-api:${SYN_VERSION:-latest}\n"
                "  g:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "pinned by a variable",
            ),
            (
                "services:\n  a:\n    image: ghcr.io/syntropic137/syn-api\n"
                "  g:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "not pinned",
            ),
        ],
    )
    def test_an_unrecognised_compose_exits_nonzero_and_writes_nothing(
        self, compose: str, reason: str, tmp_path: Path
    ) -> None:
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text(compose)
        staged = tmp_path / "staged.yaml"

        proc = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(deployed), str(staged)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 1
        assert reason in proc.stderr
        assert not staged.exists()
