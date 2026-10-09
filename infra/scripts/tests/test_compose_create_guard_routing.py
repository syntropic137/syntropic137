"""The socket proxy must send every container create to docker-create-guard (#1806).

The proxy filters on method and path only, so a create body asking for
``Privileged`` or a bind of ``/`` reached the daemon untouched. Each compose
file patches haproxy to route ``POST /containers/create`` to the guard
service. This runs the real entrypoint transformation from each compose file
against a template shaped like the proxy's, then evaluates the routing rule.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = [
    _ROOT / "docker" / "docker-compose.yaml",
    _ROOT / "docker" / "docker-compose.syntropic137.yaml",
]
# The tail of tecnativa/docker-socket-proxy 0.3.0's haproxy.cfg frontend.
_TEMPLATE = (
    "frontend dockerfrontend\n"
    "    http-request deny unless METH_GET || { env(POST) -m bool }\n"
    "    http-request deny\n"
    "    default_backend dockerbackend\n"
    "\n"
    "    use_backend docker-events if { path,url_dec -m reg -i ^(/v[\\d\\.]+)?/events }\n"
)
_ROUTE = re.compile(
    r"use_backend docker-create-guard if \{ method (\w+) \} \{ path,url_dec -m reg -i (\S+) \}"
)


def _patched(compose: Path, tmp_path: Path) -> str:
    service = yaml.safe_load(compose.read_text())["services"]["docker-socket-proxy"]
    shell, flags, script = service["entrypoint"][:3]
    template = tmp_path / "haproxy.cfg.template"
    template.write_text(_TEMPLATE)
    script = script.replace("$$", "$").replace(
        "/usr/local/etc/haproxy/haproxy.cfg.template", str(template)
    )
    script = script.replace("/tmp/capture-haproxy.template", str(tmp_path / "out.template"))
    script = script.replace('exec /docker-entrypoint.sh "$@"', "true")
    subprocess.run([shell, flags, script], check=True)
    return template.read_text()


def _routed(config: str, method: str, path: str) -> bool:
    match = _ROUTE.search(config)
    assert match is not None, "no use_backend docker-create-guard rule was inserted"
    route_method, pattern = match.groups()
    return method == route_method and re.search(pattern, unquote(path), re.IGNORECASE) is not None


@pytest.mark.parametrize("compose", _COMPOSE, ids=lambda p: p.name)
class TestCreateRouting:
    @pytest.mark.parametrize(
        "path",
        [
            "/containers/create",
            "/v1.47/containers/create",
            "/v1.47/containers/create/",
            "/v1.47/CONTAINERS/Create",
            "/v1.47/containers/%63reate",
        ],
    )
    def test_every_create_spelling_is_routed(self, compose: Path, tmp_path: Path, path: str) -> None:
        assert _routed(_patched(compose, tmp_path), "POST", path)

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/v1.47/containers/json"),
            ("POST", "/v1.47/containers/abc/start"),
            ("POST", "/v1.47/containers/abc/exec"),
            ("POST", "/v1.47/images/create"),
        ],
    )
    def test_other_requests_keep_the_default_backend(
        self, compose: Path, tmp_path: Path, method: str, path: str
    ) -> None:
        assert not _routed(_patched(compose, tmp_path), method, path)

    def test_route_sits_in_the_frontend_and_backend_is_defined(
        self, compose: Path, tmp_path: Path
    ) -> None:
        config = _patched(compose, tmp_path)
        frontend = config.split("frontend dockerfrontend", 1)[1].split("\nresolvers ", 1)[0]
        assert "use_backend docker-create-guard" in frontend
        assert "backend docker-create-guard\n    server guard docker-create-guard:2375" in config

    def test_guard_service_holds_the_socket_and_no_capabilities(self, compose: Path, tmp_path: Path) -> None:
        guard = yaml.safe_load(compose.read_text())["services"]["docker-create-guard"]
        assert guard["command"] == ["python", "-m", "syn_adapters.docker_create_guard"]
        assert "/var/run/docker.sock:/var/run/docker.sock" in guard["volumes"]
        assert guard["cap_drop"] == ["ALL"] and "cap_add" not in guard
        assert guard["networks"] == ["docker-proxy"]
        assert guard["environment"]["SYN_WORKSPACE_HOST_DIR"] == "${SYN_INSTALL_DIR:-${PWD}}/workspaces"
