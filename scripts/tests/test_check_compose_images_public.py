"""Unit tests for the anonymous-pull gate on compose images.

The network probe is not exercised here; these drive the parts that decide
WHICH refs are asked about and WHAT counts as a pass, against the real compose
files, because a gate that silently skips the image that broke is no gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.check_compose_images_public import (
    COMPOSE_FILES,
    ImageRef,
    PullResult,
    evaluate,
    fixed_image_refs,
    parse_ref,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize(
    ("ref", "registry", "repository", "tag", "digest"),
    [
        ("redis:7.2.5-alpine", "registry-1.docker.io", "library/redis", "7.2.5-alpine", None),
        (
            "cloudflare/cloudflared:2026.2.0",
            "registry-1.docker.io",
            "cloudflare/cloudflared",
            "2026.2.0",
            None,
        ),
        ("docker.io/library/redis", "registry-1.docker.io", "library/redis", None, None),
        (
            f"quay.io/minio/minio:RELEASE.X@{_DIGEST}",
            "quay.io",
            "minio/minio",
            "RELEASE.X",
            _DIGEST,
        ),
        (f"ghcr.io/syntropic137/minio@{_DIGEST}", "ghcr.io", "syntropic137/minio", None, _DIGEST),
        ("localhost:5000/foo:1", "localhost:5000", "foo", "1", None),
    ],
)
def test_parse_ref_splits_like_docker(
    ref: str, registry: str, repository: str, tag: str | None, digest: str | None
) -> None:
    parsed = parse_ref(ref)
    assert (parsed.registry, parsed.repository, parsed.tag, parsed.digest) == (
        registry,
        repository,
        tag,
        digest,
    )


def test_a_pinned_ref_is_asked_for_by_digest_not_tag() -> None:
    assert parse_ref(f"quay.io/minio/minio:RELEASE.X@{_DIGEST}").reference == _DIGEST


def test_the_real_compose_files_include_the_minio_image_and_skip_templated_app_images() -> None:
    texts = [(_ROOT / p).read_text() for p in COMPOSE_FILES]
    refs = fixed_image_refs(texts)
    repos = {r.repository for r in refs}

    assert "syntropic137/minio" in repos, "the image that broke main must be checked"
    assert not any("$" in r.original for r in refs)
    assert not any(r.repository == "syntropic137/syn-api" for r in refs)
    assert len({r.original for r in refs}) == len(refs), "each ref probed once"


def _ref(digest: str | None = _DIGEST) -> ImageRef:
    return parse_ref(f"ghcr.io/syntropic137/minio:RELEASE.X@{digest}" if digest else "redis:7")


def test_unauthorized_fails_the_gate() -> None:
    code, lines = evaluate([PullResult(_ref(), 401, None, "HTTP 401")])
    assert code == 1
    assert "HTTP 401" in lines[0]


def test_a_digest_the_registry_does_not_serve_fails_the_gate() -> None:
    code, _ = evaluate([PullResult(_ref(), 200, "sha256:" + "b" * 64)])
    assert code == 1


def test_an_unreachable_registry_fails_the_gate() -> None:
    code, _ = evaluate([PullResult(_ref(), None, None, "timed out")])
    assert code == 1


def test_a_pullable_pinned_and_a_pullable_tagged_image_pass() -> None:
    code, _ = evaluate(
        [PullResult(_ref(), 200, _DIGEST), PullResult(_ref(None), 200, "sha256:" + "c" * 64)]
    )
    assert code == 0
