"""The rehearsal override renames every pinned name the candidate compose has (#1310 1.6).

``check_rendered`` refuses any container, volume or network named outside the
rehearsal project, so a pinned name the override misses stops the rehearsal
before the upgrade, or, were the check ever loosened, reaches production. This
runs the script's own ``write_override`` against the candidate compose and a
release before the executor, and checks every name the base file pins.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rehearse_upgrade.sh"
COMPOSE = ROOT / "docker" / "docker-compose.syntropic137.yaml"
PROJECT = "syn137rehearse-test"


def _override(
    tmp_path: Path, compose: dict[str, object]
) -> dict[str, dict[str, dict[str, object]]]:
    script = SCRIPT.read_text()
    functions = script[
        script.index("REHEARSAL_PATH=") : script.index(
            'if [ "$VERIFY_ONLY" = 0 ]; then\n# --- prepare'
        )
    ]
    (tmp_path / "docker-compose.syntropic137.yaml").write_text(yaml.safe_dump(compose))
    env = dict(os.environ, WORK=str(tmp_path), PROJECT=PROJECT, PORT="38000", CRED_VARS="")
    subprocess.run(
        ["bash", "-c", functions + '\nwrite_override "$WORK" candidate-api candidate-collector ""'],
        env=env,
        check=True,
    )
    return yaml.load((tmp_path / "override.yaml").read_text(), Loader=yaml.BaseLoader)


def _candidate() -> dict[str, dict[str, dict[str, object]]]:
    return yaml.safe_load(COMPOSE.read_text())


def test_every_pinned_name_in_the_candidate_is_renamed_into_the_project(tmp_path: Path) -> None:
    compose = _candidate()
    override = _override(tmp_path, compose)
    assert "executor" in compose["services"]
    for name, service in compose["services"].items():
        if "container_name" in service:
            assert override["services"][name]["container_name"] == f"{PROJECT}-{name}"
    for name, volume in compose["volumes"].items():
        if volume and "name" in volume:
            assert override["volumes"][name]["name"].startswith(f"{PROJECT}_")


def test_the_executor_is_never_started_by_the_rehearsal(tmp_path: Path) -> None:
    override = _override(tmp_path, _candidate())
    assert override["services"]["executor"]["profiles"] == ["rehearsal-disabled"]


def test_a_release_without_the_executor_gets_no_executor_service(tmp_path: Path) -> None:
    """An override naming a service its base lacks fails to render (v1.0.0)."""
    compose = _candidate()
    del compose["services"]["executor"]
    override = _override(tmp_path, compose)
    assert "executor" not in override["services"]
