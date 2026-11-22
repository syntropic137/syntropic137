"""A workflow that cannot start as it is declared (#1003).

Not an admission refusal: nothing clears this on its own. A process manager
that is asked to start such a workflow fails the work, and records WHY, because
the reason is the only thing an operator can act on. ``str(exc)`` is that
reason, so a subclass must only ever carry operator-safe text - never an
infrastructure error, which can carry a DSN.
"""

from __future__ import annotations


class WorkflowNotStartableError(Exception):
    """The stored workflow declares something this platform cannot start; fix it, then retry."""
