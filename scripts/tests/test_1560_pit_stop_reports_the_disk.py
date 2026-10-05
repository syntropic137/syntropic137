"""The pit stop shows free space on the data volume (#1560).

/health already judges the disk; the deploy is where an operator is watching,
and it is about to `docker load` two images onto that same volume. So the
precheck prints the figure and the state before anything ships, and again after
the swap. It reports and never gates: the refusal lives in the API.

Runs the script's own program against /health bodies, the way the version
check is tested, so a change to the script is a change to what is tested.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"


def _disk_program() -> str:
    script = _SCRIPT.read_text()
    start = script.index("python3 - \"$TMP/health.json\" <<'DISK'")
    body_start = script.index("\n", start) + 1
    return script[body_start : script.index("\nDISK\n", body_start)]


def _disk(state: str, free_percent: float | None) -> dict[str, object]:
    return {
        "path": "/workspaces",
        "state": state,
        "free_percent": free_percent,
        "free_bytes": None if free_percent is None else 1,
        "degraded_below_percent": 10.0,
        "refuse_admission_below_percent": 5.0,
    }


def _report(tmp_path: Path, body: dict[str, object]) -> subprocess.CompletedProcess[str]:
    payload = tmp_path / "health.json"
    payload.write_text(json.dumps(body))
    return subprocess.run(
        [sys.executable, "-", str(payload)],
        input=_disk_program(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_healthy_disk_shows_its_free_space_and_is_not_marked(tmp_path: Path) -> None:
    result = _report(tmp_path, {"status": "healthy", "disk": _disk("ok", 42.25)})
    assert result.returncode == 0, result.stderr
    assert "/workspaces 42.2% free state=ok" in result.stdout
    assert "DEGRADED" not in result.stdout


@pytest.mark.parametrize(
    ("state", "free_percent", "shown"),
    [
        ("low", 8.0, "8.0% free state=low"),
        ("critical", 3.0, "3.0% free state=critical"),
        ("unmeasurable", None, "unmeasurable state=unmeasurable"),
    ],
)
def test_a_degraded_disk_is_shown_and_marked_but_does_not_gate(
    tmp_path: Path, state: str, free_percent: float | None, shown: str
) -> None:
    result = _report(tmp_path, {"status": "degraded", "disk": _disk(state, free_percent)})
    assert result.returncode == 0, result.stderr
    assert shown in result.stdout
    assert "DEGRADED" in result.stdout


def test_an_api_without_the_disk_block_says_so(tmp_path: Path) -> None:
    result = _report(tmp_path, {"status": "healthy"})
    assert result.returncode == 0, result.stderr
    assert "not reported" in result.stdout


def test_the_disk_is_shown_before_images_are_shipped_and_after_the_swap() -> None:
    lines = _SCRIPT.read_text().splitlines()
    calls = [i for i, line in enumerate(lines) if line.strip() == "disk_space"]
    ship = next(i for i, line in enumerate(lines) if 'step "ship:' in line)
    swap = next(i for i, line in enumerate(lines) if 'step "swap:' in line)
    assert len(calls) == 2, f"expected disk_space called twice, found {len(calls)}"
    assert calls[0] < ship
    assert calls[1] > swap
