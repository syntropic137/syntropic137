"""Every third-party image our compose files pull must pull anonymously.

WHY THIS EXISTS. On 2026-09-24 ``quay.io/minio/minio`` stopped serving
anonymous pulls (``401 UNAUTHORIZED``), two days after Docker Hub's
``minio/minio`` did the same. The pin never changed, so nothing in the diff
said anything; the post-merge smoke test was the first thing to notice, and
every fresh selfhost ``compose up`` failed the same way. We now mirror MinIO to
``ghcr.io/syntropic137/minio``, whose package must stay PUBLIC - a GHCR package
is private by default, and a private one fails with the same error.

This asks each registry, WITHOUT credentials (a developer's ``docker login``
would hide exactly this failure), for the manifest every fixed image ref names.
A ref pinned by digest must also resolve to that digest.

Refs templated on ``${...}`` (our own app images, versioned per release) are
out of scope: the release pipeline publishes those, and a local beta tag is
legitimately absent from the registry.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

#: Every compose file and overlay, discovered rather than listed: a list is
#: how an overlay's new image goes unchecked (codex review, PR #1416).
COMPOSE_GLOB = "docker/docker-compose*.yaml"

_IMAGE_LINE = re.compile(r"^\s*image:\s*[\"']?([^\s\"'#]+)", re.MULTILINE)
_TIMEOUT_SECONDS = 30
_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
_DOCKER_HUB = "registry-1.docker.io"
#: One retry for a transport error or a 5xx - a registry hiccup, not a verdict.
#: 401/403/404 are answers about the image and are never retried.
_ATTEMPTS = 2


@dataclass(frozen=True)
class ImageRef:
    """An image reference split into the parts the registry API needs."""

    original: str
    registry: str
    repository: str
    tag: str | None
    digest: str | None

    @property
    def reference(self) -> str:
        """What to ask the manifest endpoint for: the digest when pinned."""
        return self.digest or self.tag or "latest"


@dataclass(frozen=True)
class PullResult:
    ref: ImageRef
    status: int | None
    served_digest: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        if self.status != 200:
            return False
        return self.ref.digest is None or self.served_digest == self.ref.digest


def parse_ref(ref: str) -> ImageRef:
    """Split ``[registry/]repo[:tag][@digest]`` the way docker does."""
    rest, _, digest = ref.partition("@")
    first, sep, remainder = rest.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        registry, path = first, remainder
    else:
        registry, path = _DOCKER_HUB, rest
    if registry == "docker.io":
        registry = _DOCKER_HUB
    repository, tag = path, None
    last = path.rsplit("/", 1)[-1]
    if ":" in last:
        repository, tag = path.rsplit(":", 1)
    if registry == _DOCKER_HUB and "/" not in repository:
        repository = f"library/{repository}"
    return ImageRef(ref, registry, repository, tag, digest or None)


def fixed_image_refs(compose_texts: list[str]) -> list[ImageRef]:
    """Every distinct image ref that is not templated on an env var."""
    seen: dict[str, ImageRef] = {}
    for text in compose_texts:
        for raw in _IMAGE_LINE.findall(text):
            if "$" in raw:
                continue
            seen.setdefault(raw, parse_ref(raw))
    return list(seen.values())


def _bearer_challenge(header: str) -> dict[str, str]:
    return dict(re.findall(r'(\w+)="([^"]*)"', header))


def _anonymous_token(ref: ImageRef) -> str | None:
    """Follow the registry's Bearer challenge with no credentials at all."""
    try:
        urllib.request.urlopen(f"https://{ref.registry}/v2/", timeout=_TIMEOUT_SECONDS)
        return None  # registry needs no token
    except urllib.error.HTTPError as exc:
        challenge = exc.headers.get("WWW-Authenticate", "")
    params = _bearer_challenge(challenge)
    realm = params.pop("realm", None)
    if realm is None:
        return None
    params["scope"] = f"repository:{ref.repository}:pull"
    url = f"{realm}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:
        body = json.loads(resp.read())
    token = body.get("token") or body.get("access_token")
    return str(token) if token else None


def compose_files(root: Path) -> list[Path]:
    return sorted(root.glob(COMPOSE_GLOB))


def probe(ref: ImageRef) -> PullResult:
    result = _probe_once(ref)
    for _ in range(_ATTEMPTS - 1):
        if result.status is not None and result.status < 500:
            break
        result = _probe_once(ref)
    return result


def _probe_once(ref: ImageRef) -> PullResult:
    try:
        token = _anonymous_token(ref)
        req = urllib.request.Request(
            f"https://{ref.registry}/v2/{ref.repository}/manifests/{ref.reference}",
            method="HEAD",
            headers={"Accept": _MANIFEST_ACCEPT},
        )
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return PullResult(ref, resp.status, resp.headers.get("Docker-Content-Digest"))
    except urllib.error.HTTPError as exc:
        return PullResult(ref, exc.code, None, f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return PullResult(ref, None, None, str(exc))


def evaluate(results: list[PullResult]) -> tuple[int, list[str]]:
    lines: list[str] = []
    failed = 0
    for r in results:
        if r.ok:
            lines.append(f"  [OK ] {r.ref.original}")
            continue
        failed += 1
        if r.status == 200:
            why = f"served {r.served_digest}, pinned {r.ref.digest}"
        else:
            why = r.error or f"HTTP {r.status}"
        lines.append(f"  [BAD] {r.ref.original}: {why}")
    if failed:
        lines.append(
            f"{failed} image(s) cannot be pulled anonymously. A fresh `compose up` "
            "fails on them. If the upstream withdrew public pulls, mirror the pinned "
            "bytes to ghcr.io/syntropic137 (see infra/README.md 'MinIO image mirror'); "
            "if it is our package, make it public."
        )
    else:
        lines.append(f"All {len(results)} fixed compose image(s) pull anonymously.")
    return (1 if failed else 0), lines


def main() -> int:
    texts = [p.read_text() for p in compose_files(Path.cwd())]
    code, lines = evaluate([probe(ref) for ref in fixed_image_refs(texts)])
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
