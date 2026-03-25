"""Service credential configuration for proxy-side credential injection (ISS-43).

Defines which external services the Envoy proxy should inject credentials for.
Each service maps hosts to header names and templates. The proxy reads credentials
from its own environment variables — agent containers never see API keys.

Phase 1: Single shared key via env vars on proxy container.
Phase 2: Per-execution credentials via Redis credential store.

Usage:
    from syn_shared.settings.credentials import get_service_registry

    registry = get_service_registry()
    for host, config in registry.items():
        print(f"{host} -> {config.service_name}: {config.header_name}")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from syn_shared.env_constants import ENV_ANTHROPIC_API_KEY, ENV_CLAUDE_CODE_OAUTH_TOKEN

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceCredentialConfig:
    """Maps a service to its credential injection parameters.

    Attributes:
        service_name: Logical name (e.g., "anthropic", "github").
        hosts: Hostnames that route to this service.
        header_name: HTTP header to inject (e.g., "x-api-key", "Authorization").
        header_template: Template for the header value. Use ``{value}`` as placeholder.
        env_var: Primary environment variable holding the credential.
        oauth_env_var: Alternative OAuth env var (takes priority when set).
        oauth_header_template: Header template when using OAuth credential.
    """

    service_name: str
    hosts: tuple[str, ...]
    header_name: str
    header_template: str
    env_var: str
    oauth_env_var: str | None = None
    oauth_header_template: str | None = None


# Built-in service definitions
ANTHROPIC_SERVICE = ServiceCredentialConfig(
    service_name="anthropic",
    hosts=("api.anthropic.com",),
    header_name="x-api-key",
    header_template="{value}",
    env_var=ENV_ANTHROPIC_API_KEY,
    oauth_env_var=ENV_CLAUDE_CODE_OAUTH_TOKEN,
    oauth_header_template="Bearer {value}",
)

GITHUB_SERVICE = ServiceCredentialConfig(
    service_name="github",
    hosts=("api.github.com", "github.com", "raw.githubusercontent.com"),
    header_name="Authorization",
    header_template="Bearer {value}",
    env_var="SYN_GITHUB_PRIVATE_KEY",
)

# Hosts allowed through the proxy without credential injection
PASSTHROUGH_HOSTS: frozenset[str] = frozenset(
    {
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
    }
)

BUILTIN_SERVICES: tuple[ServiceCredentialConfig, ...] = (
    ANTHROPIC_SERVICE,
    GITHUB_SERVICE,
)


def _load_extra_services(registry: dict[str, ServiceCredentialConfig]) -> None:
    """Parse SYN_PROXY_EXTRA_SERVICES env var and add entries to *registry*."""
    extra_json = os.getenv("SYN_PROXY_EXTRA_SERVICES", "")
    if not extra_json.strip():
        return
    try:
        extras = json.loads(extra_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse SYN_PROXY_EXTRA_SERVICES — ignoring extra services")
        return

    for entry in extras:
        try:
            svc = ServiceCredentialConfig(
                service_name=entry["service_name"],
                hosts=tuple(entry["hosts"]),
                header_name=entry["header_name"],
                header_template=entry.get("header_template", "{value}"),
                env_var=entry["env_var"],
                oauth_env_var=entry.get("oauth_env_var"),
                oauth_header_template=entry.get("oauth_header_template"),
            )
            for host in svc.hosts:
                registry[host] = svc
        except (KeyError, TypeError):
            logger.warning("Skipping malformed extra service entry: %s", entry)


def get_service_registry() -> dict[str, ServiceCredentialConfig]:
    """Build host → ServiceCredentialConfig mapping from built-in + extra services.

    Extra services can be added via the ``SYN_PROXY_EXTRA_SERVICES`` env var,
    which accepts a JSON array of objects with the same fields as
    ``ServiceCredentialConfig``.

    Returns:
        Mapping of hostname to its credential config.
    """
    registry: dict[str, ServiceCredentialConfig] = {}

    for service in BUILTIN_SERVICES:
        for host in service.hosts:
            registry[host] = service

    _load_extra_services(registry)

    return registry
