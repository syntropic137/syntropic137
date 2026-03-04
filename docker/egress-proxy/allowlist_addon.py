"""Mitmproxy addon for network allowlist enforcement.

This addon blocks traffic to hosts not in the allowlist.
Used by Syn137 to restrict agent network access to only approved services.

See ADR-021: Isolated Workspace Architecture - Network Allowlist

Environment Variables:
    ALLOWED_HOSTS: Comma-separated list of allowed hostnames
                   Example: "api.anthropic.com,github.com,pypi.org"

Usage:
    mitmdump -s allowlist_addon.py
"""

import logging
import os
import re

from mitmproxy import http

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("allowlist")


class AllowlistAddon:
    """Mitmproxy addon that enforces a host allowlist.

    Blocks HTTP/HTTPS requests to hosts not in the allowlist.
    Supports exact matches and wildcard subdomains.

    Examples:
        "github.com" - matches github.com only
        "*.github.com" - matches api.github.com, raw.github.com, etc.
        "*.pythonhosted.org" - matches files.pythonhosted.org, etc.
    """

    def __init__(self) -> None:
        """Initialize the allowlist from environment."""
        self.allowed_hosts: set[str] = set()
        self.allowed_patterns: list[re.Pattern] = []
        self._load_allowlist()

    def _load_allowlist(self) -> None:
        """Load allowed hosts from environment variable."""
        hosts_str = os.environ.get("ALLOWED_HOSTS", "")

        if not hosts_str:
            logger.warning("ALLOWED_HOSTS not set - blocking all traffic!")
            return

        for host in hosts_str.split(","):
            host = host.strip().lower()
            if not host:
                continue

            if host.startswith("*."):
                # Wildcard pattern: *.example.com
                pattern = re.compile(
                    r"^(.+\.)?" + re.escape(host[2:]) + r"$",
                    re.IGNORECASE,
                )
                self.allowed_patterns.append(pattern)
                logger.info(f"Added wildcard pattern: {host}")
            else:
                # Exact match
                self.allowed_hosts.add(host)
                logger.info(f"Added allowed host: {host}")

        logger.info(
            f"Allowlist loaded: {len(self.allowed_hosts)} exact, "
            f"{len(self.allowed_patterns)} patterns"
        )

    def _is_allowed(self, host: str) -> bool:
        """Check if a host is in the allowlist.

        Args:
            host: Hostname to check

        Returns:
            True if allowed, False otherwise
        """
        host = host.lower()

        # Remove port if present
        if ":" in host:
            host = host.split(":")[0]

        # Check exact match
        if host in self.allowed_hosts:
            return True

        # Check wildcard patterns
        return any(pattern.match(host) for pattern in self.allowed_patterns)

    def request(self, flow: http.HTTPFlow) -> None:
        """Handle HTTP request - block if not in allowlist.

        Args:
            flow: The HTTP flow
        """
        host = flow.request.pretty_host

        if self._is_allowed(host):
            logger.debug(f"ALLOWED: {flow.request.method} {host}{flow.request.path}")
            return

        # Block the request
        logger.warning(f"BLOCKED: {flow.request.method} {host}{flow.request.path}")

        flow.response = http.Response.make(
            403,
            b"Blocked by Syn137 Egress Proxy: Host not in allowlist",
            {
                "Content-Type": "text/plain",
                "X-Syn-Blocked": "true",
                "X-Syn-Blocked-Host": host,
            },
        )


# Register the addon
addons = [AllowlistAddon()]
