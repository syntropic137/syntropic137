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
