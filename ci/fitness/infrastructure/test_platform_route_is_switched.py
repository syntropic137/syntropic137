"""The workspace -> API route exists only while platform access is ON (ADR-072).

Every Envoy route that forwards to ``syn_platform_api`` must be gated on the
runtime key that ``entrypoint.sh`` writes from ``SYN_PLATFORM_ACCESS_ENABLED``,
defaulting to 0%. A route added without the gate forwards workspace traffic to
the API with the setting OFF, which the API then has to refuse; with the gate
nothing is forwarded at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.architecture

_SIDECAR = Path(__file__).resolve().parents[3] / "docker" / "sidecar-proxy"
_KEY = "syn_platform.access_enabled"


def _platform_routes() -> list[dict[str, object]]:
    config = yaml.safe_load((_SIDECAR / "envoy.yaml").read_text())
    routes: list[dict[str, object]] = []
    for listener in config["static_resources"]["listeners"]:
        for chain in listener["filter_chains"]:
            for net_filter in chain["filters"]:
                route_config = net_filter["typed_config"].get("route_config", {})
                for host in route_config.get("virtual_hosts", []):
                    routes.extend(
                        r
                        for r in host["routes"]
                        if r.get("route", {}).get("cluster") == "syn_platform_api"
                    )
    return routes


def test_every_platform_route_is_off_unless_switched_on() -> None:
    routes = _platform_routes()
    assert routes, "no route forwards to syn_platform_api; did the cluster get renamed?"
    for route in routes:
        fraction = route["match"].get("runtime_fraction")  # type: ignore[union-attr]
        assert fraction is not None, f"ungated platform route: {route['match']}"
        assert fraction["runtime_key"] == _KEY
        assert fraction["default_value"]["numerator"] == 0


def test_the_switch_is_written_where_envoy_reads_it() -> None:
    config = yaml.safe_load((_SIDECAR / "envoy.yaml").read_text())
    (disk,) = [
        layer["disk_layer"]
        for layer in config["layered_runtime"]["layers"]
        if "disk_layer" in layer
    ]
    switch = f"{disk['symlink_root']}/{disk['subdirectory']}/{_KEY.replace('.', '/')}"
    assert f"switch={switch}\n" in (_SIDECAR / "entrypoint.sh").read_text()
    assert "syn-envoy-entrypoint.sh" in (_SIDECAR / "Dockerfile").read_text()


def test_the_switch_cannot_be_flipped_through_the_admin_port() -> None:
    # 9901 is reachable from agent-net (smoke-test probes it from there). An
    # admin runtime layer would let a workspace POST /runtime_modify and open
    # the platform route while SYN_PLATFORM_ACCESS_ENABLED is false.
    config = yaml.safe_load((_SIDECAR / "envoy.yaml").read_text())
    layers = config["layered_runtime"]["layers"]
    assert not [layer for layer in layers if "admin_layer" in layer]


def test_the_admin_interface_is_loopback_only_and_9901_serves_only_ready() -> None:
    # Admin on an agent-net address would let a workspace POST /logging and
    # make Envoy print other workspaces' Authorization headers (their platform
    # tokens), or POST /quitquitquit. 9901 stays reachable for /ready only.
    config = yaml.safe_load((_SIDECAR / "envoy.yaml").read_text())
    assert config["admin"]["address"]["socket_address"]["address"] == "127.0.0.1"
    (ready,) = [
        listener
        for listener in config["static_resources"]["listeners"]
        if listener["address"]["socket_address"]["port_value"] == 9901
    ]
    (chain,) = ready["filter_chains"]
    (hcm,) = chain["filters"]
    (host,) = hcm["typed_config"]["route_config"]["virtual_hosts"]
    forwarded = [r for r in host["routes"] if "route" in r]
    assert [r["match"]["path"] for r in forwarded] == ["/ready"]
    assert all("direct_response" in r for r in host["routes"] if "route" not in r)
