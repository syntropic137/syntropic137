"""The gateway access log must carry request and upstream timings (#1583).

A dashboard stall could not be attributed to the API or to the tunnel because
nginx logged with its stock ``main`` format, which has no timing at all. The
fix is a ``log_format`` with the timings appended - and, just as much, every
server block naming it. A correct format nobody uses leaves the log exactly as
blind as before while a test on the format alone passes, so these tests check
the definition, every consumer of it, and the Dockerfile hop that puts the
definition in front of the server blocks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEWAY_IMAGE = _REPO_ROOT / "infra" / "docker" / "images" / "gateway"
_FORMAT_NAME = "syn_timed"

#: nginx's stock ``main`` format, in order. The timed format must begin with
#: exactly this so a reader of the old log keeps finding every field where it was.
_MAIN_FORMAT = (
    '$remote_addr - $remote_user [$time_local] "$request" '
    '$status $body_bytes_sent "$http_referer" '
    '"$http_user_agent" "$http_x_forwarded_for"'
)

_TIMING_VARIABLES = (
    "$request_time",
    "$upstream_response_time",
    "$upstream_connect_time",
    "$upstream_header_time",
)

#: Every file nginx reads as config, plus the entrypoint that generates more.
_CONFIG_FILES = [
    *sorted(
        p
        for p in _GATEWAY_IMAGE.iterdir()
        if p.suffix == ".conf" or p.name.startswith("nginx.conf")
    ),
    _GATEWAY_IMAGE / "docker-entrypoint.sh",
]


def _log_format_definitions() -> list[tuple[Path, str]]:
    """Every ``log_format`` directive in the gateway, with its quoted pieces joined."""
    found: list[tuple[Path, str]] = []
    for path in _CONFIG_FILES:
        for match in re.finditer(r"^\s*log_format\s+(\S+)\s+(.*?);", path.read_text(), re.M | re.S):
            body = "".join(re.findall(r"'([^']*)'", match.group(2)))
            found.append((path, f"{match.group(1)} {body}"))
    return found


def _server_blocks(text: str) -> list[str]:
    """The text of every ``server { ... }`` block, by brace matching."""
    blocks: list[str] = []
    for match in re.finditer(r"^\s*server\s*\{", text, re.M):
        depth, i = 0, match.end() - 1
        while True:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        blocks.append(text[match.start() : i + 1])
    return blocks


def test_the_timed_format_is_defined_exactly_once() -> None:
    names = [body.split(" ", 1)[0] for _, body in _log_format_definitions()]
    assert names == [_FORMAT_NAME]


@pytest.mark.parametrize(("path", "definition"), _log_format_definitions())
def test_every_log_format_carries_all_four_timings(path: Path, definition: str) -> None:
    missing = [v for v in _TIMING_VARIABLES if not re.search(re.escape(v) + r"\b", definition)]
    assert not missing, f"{path.name} log_format lacks {missing}"


@pytest.mark.parametrize(("path", "definition"), _log_format_definitions())
def test_every_log_format_keeps_the_stock_fields_first_and_in_order(
    path: Path, definition: str
) -> None:
    body = definition.split(" ", 1)[1]
    assert body.startswith(_MAIN_FORMAT), f"{path.name} reorders or drops a stock field"


@pytest.mark.parametrize("path", [p for p in _CONFIG_FILES if _server_blocks(p.read_text())])
def test_every_server_block_logs_with_the_timed_format(path: Path) -> None:
    for block in _server_blocks(path.read_text()):
        listen = re.search(r"listen\s+([^;]+);", block)
        assert re.search(rf"^\s*access_log\s+\S+\s+{_FORMAT_NAME}\s*;", block, re.M), (
            f"{path.name} server block on {listen.group(1) if listen else '?'} "
            f"does not log with {_FORMAT_NAME}"
        )


def test_both_shipped_configs_have_server_blocks() -> None:
    """Guards the parametrization above against silently matching nothing."""
    with_servers = {p.name for p in _CONFIG_FILES if _server_blocks(p.read_text())}
    assert {"nginx.conf", "nginx.conf.dev"} <= with_servers


def test_dockerfile_loads_the_format_before_the_server_blocks() -> None:
    """nginx rejects an access_log naming a format it has not parsed yet.

    conf.d is included in sorted order, and the server blocks arrive as
    ``default.conf`` (the baked nginx.conf, or nginx.conf.dev mounted over it),
    so the format's file must sort before that name.
    """
    dockerfile = (_GATEWAY_IMAGE / "Dockerfile").read_text()
    match = re.search(r"^COPY\s+\S*/log-format\.conf\s+/etc/nginx/conf\.d/(\S+)$", dockerfile, re.M)
    assert match, "Dockerfile does not install log-format.conf into conf.d"
    assert match.group(1) < "default.conf"
