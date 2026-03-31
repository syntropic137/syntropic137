"""Fitness function: proxy hostname agreement.

Verifies that the Envoy virtual host domains, token injector allowlist,
and DEFAULT_PROXY_URL all agree on the same proxy hostname.

Drift between these three sources caused a production bug (ISS-405) where
the selfhost stack used a different container name than what the code expected,
breaking credential injection for all agents.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _envoy_anthropic_domains() -> set[str]:
    """Parse envoy.yaml and extract domains from the 'anthropic' virtual host."""
    envoy_yaml = _repo_root() / "docker" / "sidecar-proxy" / "envoy.yaml"
    with envoy_yaml.open() as f:
        config = yaml.safe_load(f)

    # Walk: static_resources -> listeners -> filter_chains -> filters -> route_config
    listeners = config.get("static_resources", {}).get("listeners", [])
    domains: set[str] = set()
    for listener in listeners:
        for fc in listener.get("filter_chains", []):
            for filt in fc.get("filters", []):
                typed_config = filt.get("typed_config", {})
                route_config = typed_config.get("route_config", {})
                for vhost in route_config.get("virtual_hosts", []):
                    if vhost.get("name") == "anthropic":
                        domains.update(vhost.get("domains", []))
    return domains


def _token_injector_anthropic_hosts() -> set[str]:
    """Parse token_injector.py and extract the _ANTHROPIC_HOSTS tuple literal."""
    injector_py = _repo_root() / "docker" / "token-injector" / "token_injector.py"
    tree = ast.parse(injector_py.read_text())

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_ANTHROPIC_HOSTS":
                    if isinstance(node.value, ast.Tuple):
                        return {
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        }
    return set()


def _default_proxy_hostname() -> str:
    """Import DEFAULT_PROXY_URL from the adapter and extract its hostname."""
    src = _repo_root() / "packages" / "syn-adapters" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from syn_adapters.workspace_backends.docker.shared_envoy_adapter import DEFAULT_PROXY_URL

    parsed = urlparse(DEFAULT_PROXY_URL)
    return parsed.hostname or ""


@pytest.mark.architecture
def test_proxy_hostname_agreement() -> None:
    """Envoy domains, token injector allowlist, and DEFAULT_PROXY_URL must agree.

    These three sources form the proxy credential injection chain:
      agent → envoy-proxy (DNS) → envoy virtual host match → ext_authz → token injector

    If the hostname in any one source differs from the others, credential injection
    silently fails: agents get 401/403 from the Anthropic API instead of a clear error.
    """
    envoy_domains = _envoy_anthropic_domains()
    injector_hosts = _token_injector_anthropic_hosts()
    proxy_hostname = _default_proxy_hostname()

    assert envoy_domains, "Could not parse any domains from envoy.yaml anthropic virtual host"
    assert injector_hosts, "Could not parse _ANTHROPIC_HOSTS from token_injector.py"
    assert proxy_hostname, "Could not extract hostname from DEFAULT_PROXY_URL"

    # The proxy service hostname must appear in envoy's virtual host domain list
    assert proxy_hostname in envoy_domains, (
        f"DEFAULT_PROXY_URL hostname '{proxy_hostname}' not found in envoy.yaml domains: "
        f"{sorted(envoy_domains)}. "
        "Agents routing to this hostname will not match any virtual host — "
        "update envoy.yaml domains to include the service name."
    )

    # The proxy service hostname must appear in the token injector allowlist
    assert proxy_hostname in injector_hosts, (
        f"DEFAULT_PROXY_URL hostname '{proxy_hostname}' not found in _ANTHROPIC_HOSTS: "
        f"{sorted(injector_hosts)}. "
        "The token injector will reject credential injection requests from agents — "
        "add the hostname to _ANTHROPIC_HOSTS in token_injector.py."
    )

    # Envoy domains and injector hosts should share the proxy hostname
    shared = envoy_domains & injector_hosts - {"api.anthropic.com", "claude.ai", "api.anthropic.com:443"}
    assert shared, (
        f"No shared proxy hostname between envoy domains {sorted(envoy_domains)} "
        f"and injector hosts {sorted(injector_hosts)}. "
        "The proxy service name must appear in both for credential injection to work."
    )
