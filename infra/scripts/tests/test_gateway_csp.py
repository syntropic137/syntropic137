"""The gateway CSP lets the feedback widget preview screenshots, and no more.

The widget renders a pasted or captured screenshot from
``URL.createObjectURL(blob)``, so its ``<img src>`` is a ``blob:`` URL. With
``img-src 'self' data:`` every preview was refused by the browser, which is how
"image upload is not working" was reported.

The gateway declares its CSP in two places, and they reach different responses:

* ``security-headers.conf`` -- included by both server blocks in
  ``nginx.conf``, so it covers the dashboard; and
* the ``location /api/v1/`` block that ``docker-entrypoint.sh`` writes, which
  needs its own copy because nginx does not inherit ``add_header`` into a
  location that declares any of its own.

Fixing one and not the other leaves half the surface broken, so both are
parsed here. Each is also checked for the one relaxation that must never ride
along with this change: ``'unsafe-eval'``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEWAY_IMAGE = _REPO_ROOT / "infra" / "docker" / "images" / "gateway"
_SECURITY_HEADERS = _GATEWAY_IMAGE / "security-headers.conf"
_ENTRYPOINT = _GATEWAY_IMAGE / "docker-entrypoint.sh"
_NGINX_CONF = _GATEWAY_IMAGE / "nginx.conf"

_CSP_HEADER = re.compile(r'add_header\s+Content-Security-Policy\s+"([^"]+)"')

_CSP_SOURCES = [
    pytest.param(_SECURITY_HEADERS, id="security-headers.conf"),
    pytest.param(_ENTRYPOINT, id="docker-entrypoint.sh"),
]


def _policies(path: Path) -> list[dict[str, list[str]]]:
    """Every CSP declared in ``path``, as directive -> source list."""
    policies: list[dict[str, list[str]]] = []
    for header in _CSP_HEADER.findall(path.read_text()):
        policy: dict[str, list[str]] = {}
        for directive in filter(str.strip, header.split(";")):
            name, *sources = directive.split()
            policy[name] = sources
        policies.append(policy)
    return policies


@pytest.mark.parametrize("path", _CSP_SOURCES)
def test_img_src_allows_blob(path: Path) -> None:
    policies = _policies(path)
    assert policies, f"no Content-Security-Policy found in {path.name}"
    for policy in policies:
        assert "blob:" in policy["img-src"], policy["img-src"]


@pytest.mark.parametrize("path", _CSP_SOURCES)
def test_blob_is_allowed_for_images_only(path: Path) -> None:
    for policy in _policies(path):
        widened = [
            name for name, sources in policy.items() if name != "img-src" and "blob:" in sources
        ]
        assert widened == []


@pytest.mark.parametrize("path", _CSP_SOURCES)
def test_no_unsafe_eval(path: Path) -> None:
    policies = _policies(path)
    assert policies
    for policy in policies:
        for name, sources in policy.items():
            assert "'unsafe-eval'" not in sources, name


def _server_blocks(conf: str) -> list[str]:
    """The body of every top-level ``server { ... }`` block, comments removed."""
    text = re.sub(r"#[^\n]*", "", conf)
    blocks: list[str] = []
    for start in re.finditer(r"^\s*server\s*\{", text, re.MULTILINE):
        depth = 0
        for index in range(start.end() - 1, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start.end() : index])
                    break
    return blocks


def test_security_headers_reach_every_server_block() -> None:
    """A correct policy in a file nginx never includes protects nothing.

    Checked per block: a global count passes when one server includes the
    file twice and the other not at all.
    """
    blocks = _server_blocks(_NGINX_CONF.read_text())
    assert len(blocks) >= 2, "expected the host and tunnel server blocks"
    for block in blocks:
        listen = re.search(r"listen\s+([^;]+);", block)
        assert "include /etc/nginx/conf.d/security-headers.conf;" in block, (
            listen.group(1) if listen else block[:80]
        )
