"""What ``E2BSandboxClient.list`` returns, named once (#1917).

A module of its own because the projection-handler fitness gate reads a bare
``list`` written beside a method named ``list`` as that method handed off as a
value; the alias keeps ``BreakerE2BClient`` free of the builtin's name.
"""

from __future__ import annotations

from agentic_isolation.providers.e2b_client import SandboxListing

type SandboxListings = list[SandboxListing]
