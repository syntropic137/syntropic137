"""The socket proxy must send every container create to docker-create-guard (#1806).

The proxy filters on method and path only, so a create body asking for
``Privileged`` or a bind of ``/`` reached the daemon untouched. The proxy's
haproxy template is generated (scripts/docker_socket_proxy_config.py) and each
compose file mounts it: the repo files by path, the published file inlined as
config content. These tests read both of those sources and evaluate the rules.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, unquote

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_BASE = _ROOT / "docker" / "docker-compose.yaml"
_PUBLISHED = _ROOT / "docker" / "docker-compose.syntropic137.yaml"
_COMPOSE = [_BASE, _PUBLISHED]
_GENERATED = _ROOT / "docker" / "generated" / "docker-socket-proxy.haproxy.cfg.template"
_TEMPLATE_TARGET = "/usr/local/etc/haproxy/haproxy.cfg.template"
_ROUTE = re.compile(
    r"use_backend docker-create-guard if \{ method (\w+) \} \{ path,url_dec -m reg -i (\S+) \}"
)


def _mounted_config(compose: Path) -> str:
    """The haproxy template this compose file puts in the proxy, as the container sees it."""
    data = yaml.safe_load(compose.read_text())
    proxy = data["services"]["docker-socket-proxy"]
    (mount,) = [m for m in proxy["configs"] if m["target"] == _TEMPLATE_TARGET]
    config = data["configs"][mount["source"]]
    if "file" in config:
        return (compose.parent / config["file"]).read_text()
    # Compose interpolates content; `$$` is a literal `$`.
    return str(config["content"]).replace("$$", "$")


@pytest.mark.parametrize("compose", _COMPOSE, ids=lambda p: p.name)
def test_every_compose_mounts_the_generated_template(compose: Path) -> None:
    """No runtime patching: the stock entrypoint renders the committed file."""
    proxy = yaml.safe_load(compose.read_text())["services"]["docker-socket-proxy"]
    assert "entrypoint" not in proxy
    assert _mounted_config(compose) == _GENERATED.read_text()


def _routed(config: str, method: str, path: str) -> bool:
    routes = _ROUTE.findall(config)
    assert routes, "no use_backend docker-create-guard rule was inserted"
    return any(
        method == route_method and re.search(pattern, unquote(path), re.IGNORECASE) is not None
        for route_method, pattern in routes
    )


_DENY = re.compile(
    r"^\s*http-request deny if \{ method POST \} \{ path,url_dec -m reg -i (\S+) \}(.*)$",
    re.MULTILINE,
)


def _denied(config: str, path: str, query: str = "", content_type: str = "") -> bool:
    """Evaluate the inserted POST deny rules; any condition this does not model fails the test."""
    frontend = config.split("frontend dockerfrontend", 1)[1]
    for pattern, condition in _DENY.findall(frontend):
        if re.search(pattern, unquote(path), re.IGNORECASE) is None:
            continue
        condition = condition.strip()
        if condition == "":
            return True
        if condition == "!{ url_param(fromImage) -m reg . }":
            if not parse_qs(query).get("fromImage", [""])[0]:
                return True
        elif condition == "{ req.hdr(content-type) -m sub -i x-www-form-urlencoded }":
            if "x-www-form-urlencoded" in content_type.lower():
                return True
        else:
            raise AssertionError(f"unmodelled deny condition {condition!r}")
    return False


@pytest.mark.parametrize("compose", _COMPOSE, ids=lambda p: p.name)
class TestImageNaming:
    """The create guard's image allowlist is a name check; the API must not be able to name images."""

    @pytest.mark.parametrize(
        ("path", "query", "content_type"),
        [
            ("/v1.47/images/load", "", ""),
            ("/images/load", "quiet=1", ""),
            ("/v1.47/images/alpine:3/tag", "repo=ghcr.io/syntropic137/x&tag=1", ""),
            ("/v1.47/images/ghcr.io/evil/x/tag", "repo=syn-sidecar-proxy", ""),
            ("/v1.47/images/%6coad", "", ""),
            ("/v1.47/images/create", "fromSrc=-&repo=ghcr.io/syntropic137/x", ""),
            ("/v1.47/images/create", "fromImage=&fromSrc=http://evil/x.tar", ""),
            (
                "/v1.47/images/create",
                "fromImage=alpine",
                "application/x-www-form-urlencoded",
            ),
        ],
    )
    def test_load_tag_and_import_are_denied(
        self, compose: Path, path: str, query: str, content_type: str
    ) -> None:
        assert _denied(_mounted_config(compose), path, query, content_type)

    @pytest.mark.parametrize(
        ("path", "query"),
        [
            ("/v1.47/images/create", "fromImage=ghcr.io/syntropic137/x&tag=1"),
            ("/images/create", "fromImage=alpine"),
            ("/v1.47/containers/create", ""),
        ],
    )
    def test_pull_and_create_are_not_denied(self, compose: Path, path: str, query: str) -> None:
        assert not _denied(_mounted_config(compose), path, query)

    def test_denies_precede_every_upstream_allow(self, compose: Path) -> None:
        frontend = _mounted_config(compose).split("frontend dockerfrontend", 1)[1]
        last_deny = max(m.start() for m in _DENY.finditer(frontend))
        assert len(_DENY.findall(frontend)) == 3
        assert last_deny < frontend.index("http-request allow")


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
            # Exec: the guard and the proxy hold the socket, so exec is checked too.
            "/v1.47/containers/abc/exec",
            "/containers/syn-docker-create-guard/exec/",
            "/v1.47/Containers/abc/%65xec",
        ],
    )
    def test_every_create_spelling_is_routed(self, compose: Path, path: str) -> None:
        assert _routed(_mounted_config(compose), "POST", path)

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/v1.47/containers/json"),
            ("POST", "/v1.47/containers/abc/start"),
            ("GET", "/v1.47/containers/abc/json"),
            ("POST", "/v1.47/exec/abc/start"),
            ("POST", "/v1.47/images/create"),
        ],
    )
    def test_other_requests_keep_the_default_backend(
        self, compose: Path, method: str, path: str
    ) -> None:
        assert not _routed(_mounted_config(compose), method, path)

    def test_route_sits_in_the_frontend_and_backend_is_defined(self, compose: Path) -> None:
        config = _mounted_config(compose)
        frontend = config.split("frontend dockerfrontend", 1)[1].split("\nresolvers ", 1)[0]
        assert "use_backend docker-create-guard" in frontend
        assert "backend docker-create-guard\n    server guard docker-create-guard:2375" in config

    def test_guard_service_holds_the_socket_and_no_capabilities(self, compose: Path) -> None:
        guard = yaml.safe_load(compose.read_text())["services"]["docker-create-guard"]
        assert guard["command"] == ["python", "-m", "syn_adapters.docker_create_guard"]
        # A stdlib-only script run by path (tested beside the guard), not `python -c`.
        assert guard["healthcheck"]["test"] == [
            "CMD",
            "python",
            "-I",
            "/app/packages/syn-adapters/src/syn_adapters/docker_create_guard/healthcheck.py",
        ]
        assert "/var/run/docker.sock:/var/run/docker.sock" in guard["volumes"]
        assert guard["cap_drop"] == ["ALL"] and "cap_add" not in guard
        assert guard["networks"] == ["docker-proxy"]
        assert (
            guard["environment"]["SYN_WORKSPACE_HOST_DIR"]
            == "${SYN_INSTALL_DIR:-${PWD}}/workspaces"
        )


def test_published_guard_sees_the_api_workspaces_root() -> None:
    """Without this mount every workspace bind is refused as unseeable."""
    services = yaml.safe_load((_ROOT / "docker" / "docker-compose.syntropic137.yaml").read_text())[
        "services"
    ]
    guard, api = services["docker-create-guard"], services["api"]
    assert (
        guard["environment"]["SYN_WORKSPACE_HOST_DIR"]
        == api["environment"]["SYN_WORKSPACE_HOST_DIR"]
    )
    mounted = guard["environment"]["SYN_WORKSPACE_CONTAINER_DIR"]
    assert mounted == api["environment"]["SYN_WORKSPACE_CONTAINER_DIR"]
    api_source = next(v.split(":")[0] for v in api["volumes"] if v.split(":")[1] == mounted)
    assert f"{api_source}:{mounted}:ro" in guard["volumes"]
