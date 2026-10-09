"""The states a workspace's session capture can end in.

Session capture is deliberately FAIL-OPEN: a store outage, a bad token, or a
timeout must never stop a workflow from running. That policy is only defensible
if the platform can afterwards answer, per execution, whether capture actually
happened - otherwise "does not block execution" quietly becomes "loses sessions
and says nothing".

This module names the answers. Deciding which one applies is
`capture_result`'s job: it reads `apss-session-exporter --json`, invoked BY THE
HOST over a channel the agent has no handle on, which is what makes the verdict
authoritative.

There used to be a second reader here, a parser for the finalizer's stderr
lines. It had no production caller and it misread verdict lines (#1779), and
that stream is one the agent can write to as well, so it could never be more
than evidence. It was deleted rather than repaired.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["CaptureState"]


class CaptureState(StrEnum):
    """What happened to this execution's sessions.

    Deliberately NOT a boolean. "Did capture work" has more than two useful
    answers, and collapsing them is how an operator ends up unable to tell a
    store outage from a misconfiguration from a run that had nothing to send.
    """

    DISABLED = "disabled"
    """No store configured. The overwhelmingly common case, and not a problem."""

    CAPTURED = "captured"
    """The sweep completed cleanly. Sessions are in the store."""

    INCOMPLETE = "incomplete"
    """The sweep ran and something did not land - failed, rejected, or oversize.

    Distinct from FAILED: the exporter worked and the STORE or a transcript was
    the problem, so retrying the same call unchanged will usually repeat it.
    """

    FAILED = "failed"
    """The exporter could not complete - non-zero exit, or a timeout.

    Usually transient (store unreachable, slow network), so this is the state
    worth retrying and the state a backfill should target.
    """

    UNKNOWN = "unknown"
    """The verdict cannot be trusted either way.

    The exporter's result was unreadable, contradicted itself, or did not match
    what the host expected. Never silently treated as success: a wrong
    "captured" is worse than an admitted "not sure", so this asks for a backfill.
    """
