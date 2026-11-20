"""The nginx images run a patched release and serve plain HTTP/1.1 only (#2335).

nginx's November 2026 security release (CVE-2026-123007 and nine more) fixes
bugs that sit in HTTP/2, HTTP/3, TLS, the resolver, the mail and stream
modules, and the PROXY protocol. The fix is nginx 1.30.7; 1.28.x gets none.

Two things keep that class of bug away from these images, and each is checked
here:

- Both nginx images build ``FROM`` 1.30.7 or later, pinned by digest, and the
  same digest, so a rebuild cannot float to another nginx and the two images
  cannot drift apart.
- No nginx config they ship turns on any of those features
  (``infra/scripts/check_nginx_features.py``). The stanzas the gateway
  entrypoint generates, the base image's ``nginx.conf`` and every include are
  checked on the rendered ``nginx -T`` by ``just skyline-gateway-smoke``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from infra.scripts.check_nginx_features import findings, main, parse

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEWAY_IMAGE = _REPO_ROOT / "infra" / "docker" / "images" / "gateway"
_DASHBOARD = _REPO_ROOT / "apps" / "syn-dashboard-ui"

_DOCKERFILES = (_GATEWAY_IMAGE / "Dockerfile", _DASHBOARD / "Dockerfile")

#: Every nginx config file either image ships.
_CONFIG_FILES = (
    *sorted(
        p
        for p in _GATEWAY_IMAGE.iterdir()
        if p.suffix == ".conf" or p.name.startswith("nginx.conf")
    ),
    _DASHBOARD / "nginx.conf",
)

#: The first nginx release with the November 2026 fixes on the stable branch.
_MIN_NGINX = (1, 30, 7)

_FROM_NGINX = re.compile(
    r"^FROM\s+nginx:(\d+)\.(\d+)\.(\d+)-alpine@(sha256:[0-9a-f]{64})\s+AS\s+\S+\s*$",
    re.M,
)


def test_the_config_files_are_found() -> None:
    """A glob that matched nothing would make every check below vacuous."""
    names = {p.name for p in _CONFIG_FILES}
    assert {"nginx.conf", "nginx.conf.dev", "security-headers.conf"} <= names
    assert all(p.is_file() for p in _CONFIG_FILES)
    assert all(parse(p.read_text()) for p in _CONFIG_FILES), "a config parsed to no directives"


@pytest.mark.parametrize("dockerfile", _DOCKERFILES, ids=lambda p: p.parent.name)
def test_nginx_base_is_patched_and_pinned_by_digest(dockerfile: Path) -> None:
    froms = [
        line
        for line in dockerfile.read_text().splitlines()
        if "nginx" in line and line.lstrip().upper().startswith("FROM")
    ]
    assert len(froms) == 1, f"{dockerfile}: expected one nginx FROM, found {froms}"
    match = _FROM_NGINX.match(froms[0])
    assert match, (
        f"{dockerfile}: nginx FROM must be nginx:X.Y.Z-alpine@sha256:<digest>, got {froms[0]!r}"
    )
    version = tuple(int(part) for part in match.groups()[:3])
    assert version >= _MIN_NGINX, f"{dockerfile}: nginx {version} predates {_MIN_NGINX}"


def test_both_images_pin_the_same_nginx() -> None:
    pins = {p: _FROM_NGINX.search(p.read_text()) for p in _DOCKERFILES}
    assert all(pins.values()), pins
    assert len({m.group(0).split(" AS ")[0] for m in pins.values() if m}) == 1, pins


@pytest.mark.parametrize("path", _CONFIG_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_affected_nginx_feature_is_enabled(path: Path) -> None:
    found = findings(parse(path.read_text()))
    assert not found, f"{path}: {found}; the gateway serves plain HTTP/1.1 only"


@pytest.mark.parametrize(
    "config",
    [
        "server { listen 80 http2; }",
        "server { listen [::]:443 ssl default_server; }",
        "server { listen 443 quic reuseport; }",
        "server { listen 8081 proxy_protocol; }",
        "http2 on;",
        "http3 on;",
        "quic_retry on;",
        "ssl on;",
        "ssl_certificate /etc/ssl/cert.pem;",
        "resolver 127.0.0.11 valid=10s;",
        "mail { }",
        "stream { }",
        # Directive separators work anywhere, not only at line starts.
        "events {} stream { server { listen 12345; } }",
        "location / { return 200; } http2 on;",
        # A # inside quotes is not a comment, so it cannot hide what follows.
        'add_header X-Test "#"; http2 on;',
        "add_header X-Test '#'; resolver 1.1.1.1;",
        # Case does not matter to nginx's directive table for these.
        "server { LISTEN 80 HTTP2; }",
    ],
)
def test_each_enabling_form_is_refused(config: str) -> None:
    assert findings(parse(config)), config


@pytest.mark.parametrize(
    "config",
    [
        "# listen 80 http2;\nlisten 80;",
        "listen 80;  # no ssl, no http2 here",
        "http2 off;",
        "ssl off;",
        'add_header Alt-Svc "h3=\\":443\\"; http2"; listen 80;',
        "add_header X-Note 'resolver stream mail';",
        "location /stream { proxy_pass http://api:8000; }",
        "location /mail/ { return 404; }",
        "proxy_http_version 1.1;",
    ],
)
def test_harmless_config_is_accepted(config: str) -> None:
    assert not findings(parse(config)), findings(parse(config))


def test_parse_keeps_quoted_separators_inside_one_argument() -> None:
    [directive] = parse('add_header X "a; b { } # c";')
    assert directive.name == "add_header"
    assert directive.args == ("X", "a; b { } # c")


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.conf"
    good.write_text("server { listen 80; }\n")
    bad = tmp_path / "bad.conf"
    bad.write_text("server {\n    listen 80;\n    http2 on;\n}\n")
    assert main([str(good)]) == 0
    assert main([str(bad)]) == 1
    assert "line 3: http2 on" in capsys.readouterr().out
