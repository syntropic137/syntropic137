"""Fitness function: proxy method agreement.

Envoy and its ext_authz check server must answer the same question about
which HTTP methods are allowed through the proxy. They are two files that
nothing links, and they diverged: envoy.yaml's virtual hosts match
``prefix: "/"`` with no method condition, while the token injector could
only answer ``do_GET`` and ``do_POST``. Every other method got a 501, which
envoy turns into a bodyless 403 for the agent, and the Claude CLI's
``HEAD /api/hello`` preflight killed phases mid-run (#1080).

The injector answers every method now, so this holds as long as envoy adds
no method condition of its own. If someone adds one, the blanket answer
stops being the matching contract and this fails, pointing at the other
half of the pair.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import functools
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Envoy's ``:method`` pseudo-header, the only way a route can filter on method.
METHOD_HEADER = ":method"

#: Methods a route match could name. Not exhaustive by design: the assertion
#: is "no method condition at all", not "not these".
_SAMPLE_METHODS = ("GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE", "TRACE")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _iter_route_matches() -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(virtual host name, route match)`` for every route in envoy.yaml."""
    envoy_yaml = _repo_root() / "docker" / "sidecar-proxy" / "envoy.yaml"
    with envoy_yaml.open() as f:
        config = yaml.safe_load(f)

    for listener in config.get("static_resources", {}).get("listeners", []):
        for filter_chain in listener.get("filter_chains", []):
            for filt in filter_chain.get("filters", []):
                route_config = filt.get("typed_config", {}).get("route_config", {})
                for vhost in route_config.get("virtual_hosts", []):
                    name = vhost.get("name", "<unnamed>")
                    for route in vhost.get("routes", []):
                        yield name, route.get("match", {})


@functools.cache
def _injector_handler() -> type:
    """Load ``TokenInjectorHandler`` from the injector script.

    Registered in ``sys.modules`` before execution because the module defines
    a dataclass under ``from __future__ import annotations``, and dataclasses
    resolves those annotations through ``sys.modules[cls.__module__]``.
    """
    path = _repo_root() / "docker" / "token-injector" / "token_injector.py"
    spec = importlib.util.spec_from_file_location("token_injector_fitness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    handler: type = module.TokenInjectorHandler
    return handler


def _handler_instance() -> object:
    """A handler that has never touched a socket.

    ``BaseHTTPRequestHandler.__init__`` serves a request, so it is bypassed;
    the only thing asked of the instance is the attribute lookup that
    ``http.server`` performs to dispatch, which is an instance-level lookup
    and so cannot be made against the class.
    """
    handler_cls = _injector_handler()
    return handler_cls.__new__(handler_cls)


@pytest.mark.architecture
def test_envoy_declares_no_method_condition() -> None:
    """No envoy route may filter on ``:method`` while the injector answers all.

    Envoy forwards the downstream method on the ext_authz check request, so
    whatever envoy routes, the injector has to be able to answer.
    """
    matches = list(_iter_route_matches())
    assert matches, "Could not parse any route matches from envoy.yaml"

    restricted = [
        (vhost, header)
        for vhost, match in matches
        for header in match.get("headers", [])
        if header.get("name", "").lower() == METHOD_HEADER
    ]

    assert not restricted, (
        f"envoy.yaml routes now filter on {METHOD_HEADER}: {restricted}. "
        "The token injector answers every method, so it would authorize methods "
        "envoy rejects and the two would be describing different proxies. Teach "
        "docker/token-injector/token_injector.py the same restriction, or drop "
        "this one. See #1080 for what the reverse mismatch cost."
    )


@pytest.mark.architecture
@pytest.mark.parametrize("method", _SAMPLE_METHODS)
def test_injector_can_answer_every_method(method: str) -> None:
    """``http.server`` resolves ``do_<METHOD>`` on the instance; so do we."""
    handler = _handler_instance()

    assert hasattr(handler, f"do_{method}"), (
        f"The token injector cannot answer {method}. http.server replies 501, "
        "and envoy turns a 5xx from the check server into a bodyless 403 for "
        "the agent (#1080). envoy.yaml puts no method condition on its routes, "
        f"so it will route {method} here."
    )


@pytest.mark.architecture
def test_injector_answers_methods_by_rule_not_by_list() -> None:
    """A method nobody has enumerated must dispatch too.

    This is what separates "answers every method" from "answers the eight
    someone remembered": an allowlist passes the parametrized check above by
    growing, and is one new method away from #1080 again.
    """
    handler = _handler_instance()

    assert hasattr(handler, "do_PROPFIND"), (
        "The injector resolves methods from a list rather than a rule. The "
        "check reads the Host header and nothing else, so it should not have "
        "an opinion about the method at all."
    )
    assert not hasattr(handler, "not_a_request_method"), (
        "Attributes outside the do_ dispatch prefix must still raise "
        "AttributeError - a handler that answers to any name at all would "
        "pass the assertion above while hiding real typos."
    )
