"""A read-only api container still has to let cosign bootstrap.

Cosign writes a TUF trust-root cache under ``$HOME/.sigstore`` BEFORE it can
verify anything. The api container runs ``read_only: true`` by design, so
without a writable mount there the workspace image signature check fails during
bootstrap and NO workflow can run at all - the signature itself is valid and is
never examined.

That shipped in v0.26.0 and bricked self-host: every execution failed at phase 1
with zero tokens and zero cost. The existing tmpfs entry beside this one was
added for the 1Password CLI; cosign's need was simply never considered, and
nothing failed until a real selfhost-profile stack tried to run a workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = [
    _ROOT / "docker" / "docker-compose.syntropic137.yaml",
    _ROOT / "docker" / "docker-compose.selfhost.yaml",
]

#: Directories cosign must be able to write before it can verify an image.
_COSIGN_CACHE = "/home/syn/.sigstore"


def _api_services() -> list[tuple[Path, dict]]:
    found = []
    for path in _COMPOSE:
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text()) or {}
        api = (doc.get("services") or {}).get("api")
        if api:
            found.append((path, api))
    return found


@pytest.mark.parametrize("path,api", _api_services(), ids=lambda v: getattr(v, "name", ""))
def test_readonly_api_can_still_write_the_cosign_cache(path: Path, api: dict) -> None:
    if not api.get("read_only"):
        pytest.skip(f"{path.name}: api is not read_only, cosign can write anywhere")

    mounts = [str(m).split(":")[0] for m in (api.get("tmpfs") or [])]
    assert _COSIGN_CACHE in mounts, (
        f"{path.name}: api is read_only but has no writable {_COSIGN_CACHE}. "
        "cosign cannot create its TUF cache, so workspace image verification "
        "fails at bootstrap and every workflow dies at phase 1 with zero "
        f"tokens. Present tmpfs mounts: {mounts}"
    )
