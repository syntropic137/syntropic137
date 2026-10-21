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

import re
from pathlib import Path

import pytest
import yaml

# CI runs `pytest -m unit`. Without this marker the module collected ZERO
# tests there, so the regression guard for the bug that bricked v0.26.0
# self-host never actually ran - it passed locally and was deselected in CI.
pytestmark = pytest.mark.unit

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


@pytest.mark.parametrize("path,api", _api_services(), ids=lambda v: getattr(v, "name", ""))
def test_the_cosign_cache_tmpfs_is_size_bounded(path: Path, api: dict) -> None:
    """An unbounded tmpfs may consume up to half of host RAM.

    Docker's default has no relation to what cosign needs, so cache growth can
    push the api container into its memory limit and get it OOM-killed - on a
    small host like the Mini that is a plausible outage, not a theoretical one.
    The sigstore TUF root is a few hundred KB.
    """
    if not api.get("read_only"):
        pytest.skip(f"{path.name}: api is not read_only")

    entries = [str(m) for m in (api.get("tmpfs") or [])]
    cosign = [m for m in entries if m.split(":")[0] == _COSIGN_CACHE]
    assert cosign, f"{path.name}: no {_COSIGN_CACHE} mount to bound"

    options = cosign[0].split(":", 1)[1] if ":" in cosign[0] else ""
    assert "size=" in options, (
        f"{path.name}: {_COSIGN_CACHE} is mounted without a size limit "
        f"({cosign[0]!r}), so it may grow to half of host RAM and OOM-kill "
        "the api container"
    )


_DOCKERFILE = _ROOT / "infra" / "docker" / "images" / "syn-api" / "Dockerfile"

#: tmpfs mounts the api user must own. Docker restores a tmpfs after a host
#: reboot as root:root 755 (a fresh one is 1777), so without uid/gid the
#: non-root api cannot write them and every run fails at bootstrap (2026-10-20).
_USER_OWNED_TMPFS = ("/home/syn/.sigstore", "/home/syn/.config")


def _api_uid() -> str:
    match = re.search(r"useradd\b[^\n]*?-u\s+(\d+)\s+syn\b", _DOCKERFILE.read_text())
    assert match, f"{_DOCKERFILE}: no `useradd ... -u <uid> syn` line to read the api uid from"
    return match.group(1)


def _tmpfs_options(entry: str) -> dict[str, str]:
    _, _, raw = entry.partition(":")
    pairs = (opt.partition("=") for opt in raw.split(",") if opt)
    return {key: value for key, _, value in pairs}


@pytest.mark.parametrize("path,api", _api_services(), ids=lambda v: getattr(v, "name", ""))
@pytest.mark.parametrize("mount", _USER_OWNED_TMPFS)
def test_user_tmpfs_is_owned_by_the_api_user(path: Path, api: dict, mount: str) -> None:
    if not api.get("read_only"):
        pytest.skip(f"{path.name}: api is not read_only")

    entries = [str(m) for m in (api.get("tmpfs") or [])]
    matches = [m for m in entries if m.split(":")[0] == mount]
    assert matches, f"{path.name}: no {mount} tmpfs"

    uid = _api_uid()
    options = _tmpfs_options(matches[0])
    assert options.get("uid") == uid and options.get("gid") == uid, (
        f"{path.name}: {mount} tmpfs is {matches[0]!r}; it must set uid={uid},gid={uid} "
        f"(the syn user in {_DOCKERFILE.name}). After a host reboot Docker restores it "
        "root:root 755 and the api cannot write it"
    )
    assert options.get("mode") == "0700", (
        f"{path.name}: {mount} tmpfs is {matches[0]!r}; it must set mode=0700 so the "
        "owner can write it and no other user can read the cache"
    )
