"""The nginx images run a patched release and serve plain HTTP/1.1 only.

nginx's November 2026 security release (CVE-2026-123007 and nine more) fixes
bugs that sit in HTTP/2, HTTP/3, TLS, the resolver, the mail and stream
modules, and the PROXY protocol. The fix is nginx 1.30.7; 1.28.x gets none.

Two things keep that class of bug away from these images, and each is checked
here:

- Both nginx images build ``FROM`` 1.30.7 or later, pinned by digest, and the
  same digest, so a rebuild cannot float to another nginx and the two images
  cannot drift apart.
- No config they ship or generate turns on any of those features. A listener
  that gained ``http2`` would make the next advisory in that code reachable,
  whatever version is pinned.

Comments are stripped before matching, so a comment naming a directive (as
the Dockerfile's does) is not mistaken for one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEWAY_IMAGE = _REPO_ROOT / "infra" / "docker" / "images" / "gateway"
_DASHBOARD = _REPO_ROOT / "apps" / "syn-dashboard-ui"

_DOCKERFILES = (_GATEWAY_IMAGE / "Dockerfile", _DASHBOARD / "Dockerfile")

#: Every file either image hands nginx as config, plus the entrypoint that
#: writes more of it at startup.
_CONFIG_FILES = (
    *sorted(
        p
        for p in _GATEWAY_IMAGE.iterdir()
        if p.suffix == ".conf" or p.name.startswith("nginx.conf")
    ),
    _GATEWAY_IMAGE / "docker-entrypoint.sh",
    _DASHBOARD / "nginx.conf",
)

#: The first nginx release with the November 2026 fixes on the stable branch.
_MIN_NGINX = (1, 30, 7)

_FROM_NGINX = re.compile(
    r"^FROM\s+nginx:(\d+)\.(\d+)\.(\d+)-alpine@(sha256:[0-9a-f]{64})\s+AS\s+\S+\s*$",
    re.M,
)

#: Directives and listen flags that enable the affected modules.
_FORBIDDEN = {
    "http2 on|listen ... http2": re.compile(r"\bhttp2\b"),
    "http3 / quic": re.compile(r"\b(?:http3|quic)\b"),
    "TLS (ssl_*, listen ... ssl)": re.compile(r"\bssl(?:_\w+)?\b"),
    "resolver": re.compile(r"\bresolver\b"),
    "mail block": re.compile(r"^\s*mail\s*\{", re.M),
    "stream block": re.compile(r"^\s*stream\s*\{", re.M),
    "PROXY protocol": re.compile(r"\bproxy_protocol\b"),
}


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_the_config_files_are_found() -> None:
    """A glob that matched nothing would make every check below vacuous."""
    names = {p.name for p in _CONFIG_FILES}
    assert {"nginx.conf", "nginx.conf.dev", "docker-entrypoint.sh"} <= names
    assert all(p.is_file() for p in _CONFIG_FILES)


@pytest.mark.parametrize("dockerfile", _DOCKERFILES, ids=lambda p: p.parent.name)
def test_nginx_base_is_patched_and_pinned_by_digest(dockerfile: Path) -> None:
    froms = [line for line in dockerfile.read_text().splitlines() if "nginx" in line and line.startswith("FROM")]
    assert len(froms) == 1, f"{dockerfile}: expected one nginx FROM, found {froms}"
    match = _FROM_NGINX.match(froms[0])
    assert match, f"{dockerfile}: nginx FROM must be nginx:X.Y.Z-alpine@sha256:<digest>, got {froms[0]!r}"
    version = tuple(int(part) for part in match.groups()[:3])
    assert version >= _MIN_NGINX, f"{dockerfile}: nginx {version} predates {_MIN_NGINX}"


def test_both_images_pin_the_same_nginx() -> None:
    pins = {p: _FROM_NGINX.search(p.read_text()) for p in _DOCKERFILES}
    assert all(pins.values()), pins
    assert len({m.group(0).split(" AS ")[0] for m in pins.values() if m}) == 1, pins


@pytest.mark.parametrize("path", _CONFIG_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_affected_nginx_feature_is_enabled(path: Path) -> None:
    text = _strip_comments(path.read_text())
    found = sorted(name for name, pattern in _FORBIDDEN.items() if pattern.search(text))
    assert not found, f"{path} enables {found}; the gateway serves plain HTTP/1.1 only"


@pytest.mark.parametrize(
    "line",
    [
        "    listen 80 http2;",
        "    http2 on;",
        "    listen 443 quic reuseport;",
        "    listen 443 ssl;",
        "    ssl_certificate /etc/ssl/cert.pem;",
        "    resolver 127.0.0.11;",
        "mail {",
        "stream {",
        "    listen 8081 proxy_protocol;",
    ],
)
def test_each_forbidden_feature_is_detected(line: str) -> None:
    """Every pattern fires on the directive it guards, so none is dead."""
    assert any(p.search(_strip_comments(line)) for p in _FORBIDDEN.values())


def test_a_commented_directive_is_not_flagged() -> None:
    text = _strip_comments("    # listen 80 http2;\n    listen 80;  # no ssl here\n")
    assert not any(p.search(text) for p in _FORBIDDEN.values())
