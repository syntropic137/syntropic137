"""The stage step must never install a partial compose file on the host.

Staging writes the repointed compose back over the deployed one. `cat` exits 0
when its input ends early, so a transfer cut short used to be renamed over the
deployed file before anything compared it, and the script then aborted with
half a compose in place (verification of #1538).

These run the stage block exactly as it is written in pit_stop.sh, against a
local directory standing in for the host and a `remote` stub that runs each
command with bash instead of ssh. One stub hands the write its whole input,
the other only the first 100 bytes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_FIXTURES = Path(__file__).parent / "fixtures" / "pit_stop"
_COMPOSE = "docker-compose.syntropic137.yaml"
_TAG = "v0.33.2-beta.1"

_START = 'step "stage: back up the deployed compose and repoint $REPOINTS"'
_END = 'if [ "$MODE" = "stage" ]; then'

_FULL = 'remote() { bash -c "$*"; }'
_SHORT = 'remote() { head -c 100 | bash -c "$*"; }'


def _stage_block() -> str:
    lines = _SCRIPT.read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if _START in line]
    ends = [i for i, line in enumerate(lines) if line.strip() == _END]
    assert len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0], (
        f"could not find the stage block in {_SCRIPT.name} between {_START!r} and {_END!r}; "
        f"if it moved, this test is no longer running it"
    )
    return "\n".join(lines[starts[0] : ends[0]])


def _counters() -> str:
    """`pins_on_tag` and `images_on_tag` as the script defines them."""
    text = _SCRIPT.read_text()
    start = text.index("pins_on_tag() {")
    end = text.index("\n}\n", text.index("images_on_tag() {", start)) + 3
    return text[start:end]


def _run_stage(
    fixture: str, host: Path, tmp: Path, stub: str, service: str = "all", compose: str | None = None
) -> subprocess.CompletedProcess[str]:
    if compose is None:
        shutil.copy(_FIXTURES / fixture, host / _COMPOSE)
    else:
        (host / _COMPOSE).write_text(compose)
    n, swapped = {"all": (2, "api gateway"), "gateway": (1, "gateway")}[service]
    preamble = f"""
set -euo pipefail
TAG={_TAG}; MODE=stage; DRY=0; HOST=fake-host; SERVICE={service}; REPOINTS=pins; ALREADY="pins already on the tag"; N={n}; SWAPPED="{swapped}"
COMPOSE_DIR={host}; COMPOSE={_COMPOSE}; TMP={tmp}; REPOINT_PY={_SCRIPT.parent / "pit_stop_repoint.py"}
step() {{ printf '==> %s\\n' "$*"; }}
die() {{ printf 'PIT STOP ABORTED: %s\\n' "$*" >&2; exit 1; }}
run() {{ "$@"; }}
{stub}
{_counters()}
"""
    return subprocess.run(
        ["bash", "-c", preamble + _stage_block(), str(_SCRIPT)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    host, tmp = tmp_path / "host", tmp_path / "tmp"
    host.mkdir()
    tmp.mkdir()
    return host, tmp


@pytest.mark.parametrize(
    ("fixture", "backup"),
    [
        ("compose-digest.yaml", "sha256-bf783882d031"),
        ("compose-tag.yaml", None),
    ],
)
def test_a_whole_transfer_stages_and_keeps_a_backup(
    fixture: str, backup: str | None, dirs: tuple[Path, Path]
) -> None:
    host, tmp = dirs
    proc = _run_stage(fixture, host, tmp, _FULL)
    assert proc.returncode == 0, proc.stderr

    deployed = (host / _COMPOSE).read_text()
    assert deployed.count(f"syn-api:{_TAG}") == 1
    assert deployed.count(f"syn-gateway:{_TAG}") == 1
    backups = list(host.glob(f"{_COMPOSE}.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == (_FIXTURES / fixture).read_text()
    if backup is not None:
        assert backups[0].name == f"{_COMPOSE}.bak-{backup}"
    assert not (host / f"{_COMPOSE}.pit-stop").exists()


@pytest.mark.parametrize("fixture", ["compose-digest.yaml", "compose-tag.yaml"])
def test_a_short_transfer_leaves_the_deployed_compose_untouched(
    fixture: str, dirs: tuple[Path, Path]
) -> None:
    host, tmp = dirs
    original = (_FIXTURES / fixture).read_bytes()
    proc = _run_stage(fixture, host, tmp, _SHORT)

    assert (host / _COMPOSE).read_bytes() == original
    assert proc.returncode != 0
    assert "did not arrive intact" in proc.stderr
    assert not (host / f"{_COMPOSE}.pit-stop").exists()
    assert not list(host.glob(f"{_COMPOSE}.bak-*"))


def test_a_gateway_only_stage_repoints_one_pin_and_passes_its_own_count(
    dirs: tuple[Path, Path],
) -> None:
    """#1310: the stage passes `--service gateway` to the repoint and then
    requires the gateway pin, alone, on the tag. syn-api keeps its digest."""
    host, tmp = dirs
    proc = _run_stage("compose-digest.yaml", host, tmp, _FULL, service="gateway")
    assert proc.returncode == 0, proc.stderr

    deployed = (host / _COMPOSE).read_text()
    assert deployed.count(f"syn-gateway:{_TAG}") == 1
    assert f"syn-api:{_TAG}" not in deployed
    assert "syn-api@sha256:bf783882d031" in deployed
    (backup,) = host.glob(f"{_COMPOSE}.bak-*")
    assert backup.name == f"{_COMPOSE}.bak-sha256-6b416d4a25dd"


def test_a_gateway_only_stage_passes_when_the_api_is_already_on_the_tag(
    dirs: tuple[Path, Path],
) -> None:
    """#1310 verification: a total over both services counted 2 here, aborted
    with 2/1, and left the new compose deployed. Only the gateway is counted."""
    host, tmp = dirs
    compose = (
        (_FIXTURES / "compose-tag.yaml")
        .read_text()
        .replace("syn-api:v0.33.1-beta.2", f"syn-api:{_TAG}")
    )
    proc = _run_stage("", host, tmp, _FULL, service="gateway", compose=compose)
    assert proc.returncode == 0, proc.stderr

    deployed = (host / _COMPOSE).read_text()
    assert deployed.count(f"syn-api:{_TAG}") == 1
    assert deployed.count(f"syn-gateway:{_TAG}") == 1
