"""Fitness function: the syn-api image ships the pinned, verified exporter.

Host-side capture replication and inventory delivery shell out to
``apss-session-exporter`` at ``SessionInventorySettings.exporter_binary``. The
syn-api image installs it from the AgentParadise/agentic-session-exporter
release, pinned to an exact version and a sha256 per arch (#2107).

Two pins name the same tool: ``PINNED_EXPORTER_VERSIONS`` records the exporter
baked into the workspace images, and the Dockerfile's ``APSS_EXPORTER_VERSION``
build arg names the one the host runs. A Dockerfile cannot import Python, so
the two cannot share one literal; this test is the drift check that makes them
one pin in effect. The host reads what the workspace exporter writes, so a
silent split between the two is exactly the bug to catch.

It also pins the install path to the runtime default, so the API resolves the
image's binary without any operator configuration.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_shared.settings.session_inventory import SessionInventorySettings
from syn_shared.settings.workspace_images import PINNED_EXPORTER_VERSIONS

_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILE = _ROOT / "infra/docker/images/syn-api/Dockerfile"
_IMAGE_BINARY = Path("/usr/local/bin/apss-session-exporter")
_ARCHES = ("AMD64", "ARM64")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _runtime_stage() -> str:
    text = _DOCKERFILE.read_text()
    marker = "AS runtime"
    assert marker in text, f"{_DOCKERFILE} has no runtime stage"
    return text.split(marker, 1)[1]


def _arg_defaults(stage: str) -> dict[str, str]:
    """Every ``ARG NAME=value`` default in the stage. Duplicates fail."""
    found: dict[str, str] = {}
    for name, value in re.findall(r"^ARG\s+(\w+)=(\S*)\s*$", stage, re.MULTILINE):
        assert name not in found, f"ARG {name} declared twice in the runtime stage"
        found[name] = value
    return found


@pytest.mark.architecture
def test_dockerfile_exporter_version_matches_workspace_pin() -> None:
    version = _arg_defaults(_runtime_stage()).get("APSS_EXPORTER_VERSION")
    assert version, "syn-api runtime stage declares no APSS_EXPORTER_VERSION default"
    assert PINNED_EXPORTER_VERSIONS, "PINNED_EXPORTER_VERSIONS is empty"
    drift = {
        str(provider): pinned
        for provider, pinned in PINNED_EXPORTER_VERSIONS.items()
        if pinned != version
    }
    assert not drift, (
        f"syn-api Dockerfile pins apss-session-exporter {version}, workspace "
        f"images pin {drift}; bump both together"
    )


@pytest.mark.architecture
@pytest.mark.parametrize("arch", _ARCHES)
def test_dockerfile_pins_a_checksum_per_arch(arch: str) -> None:
    stage = _runtime_stage()
    name = f"APSS_EXPORTER_SHA256_{arch}"
    sha = _arg_defaults(stage).get(name)
    assert sha and _SHA256.fullmatch(sha), f"{name} is not a sha256 hex digest: {sha!r}"
    # Declared is not used: the install step must select this arg for the arch.
    assert f'{arch.lower()}) SHA="${name}"' in stage, f"{name} is never selected"


@pytest.mark.architecture
def test_per_arch_checksums_differ() -> None:
    # Two arches sharing one digest means one arch was pinned to the other's
    # asset: the multi-arch release-asset pitfall.
    args = _arg_defaults(_runtime_stage())
    shas = {args.get(f"APSS_EXPORTER_SHA256_{arch}") for arch in _ARCHES}
    assert len(shas) == len(_ARCHES)


@pytest.mark.architecture
def test_install_verifies_before_installing() -> None:
    stage = _runtime_stage()
    verify = stage.find("sha256sum -c")
    install = stage.find(f"install -m 755 /tmp/apss-session-exporter {_IMAGE_BINARY}")
    assert verify != -1, "the exporter download is never checksum-verified"
    assert install != -1, f"the exporter is not installed at {_IMAGE_BINARY}"
    assert verify < install, "the exporter is installed before it is verified"
    assert "*) echo" in stage and "exit 1" in stage, "an unknown arch must fail the build"


@pytest.mark.architecture
def test_runtime_default_is_the_image_binary() -> None:
    field = SessionInventorySettings.model_fields["exporter_binary"]
    assert field.default == _IMAGE_BINARY
