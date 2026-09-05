#!/usr/bin/env python3
"""Refuse to deploy while agent executions are still in flight (#1179).

Restarting the API orphans every running execution: reconciliation marks them
``failed`` with an accurate cause, but the work is gone. On the v0.28.0-beta.7
deploy that cost roughly 45 minutes of agent work and two runs' spend, and one
of the orphaned executions had already opened a pull request whose verify phase
never ran -- an unreviewed PR that looks exactly like a finished one.

This script answers the one question an operator needs before restarting:
**what is running right now, and how long has it been running?**

    $ python3 infra/scripts/predeploy_check.py
    ✅ Nothing in flight. Safe to deploy.

    $ python3 infra/scripts/predeploy_check.py
    ⛔ 2 execution(s) in flight — deploying now would orphan them.
    ...
    exit 1

Exit codes, so a deploy script can branch on them:

===  ==========================================================================
0    Nothing running, or ``--force`` was passed.
1    Executions are in flight.
2    Could not tell (API unreachable, auth rejected, unreadable response).
===  ==========================================================================

Why 2 exists, and why "unknown" is never reported as "clear"
------------------------------------------------------------
The most dangerous possible false negative is answering "no executions running"
because the API could not be reached. That converts an unknown into a confident
wrong answer, and it happens precisely when it hurts most -- mid-deploy, with
the API already unhealthy and work most likely still in flight.

So the guarantee here is structural rather than a branch someone must remember:
:func:`running_executions` either returns a list it actually parsed from a
successful response, or raises :class:`DrainCheckUnavailable`. There is no code
path in which a failure yields an empty list. The runbook at
``docs/deployment/timescaledb-2.29-upgrade.md`` already states this rule for
the hand-rolled version of this check ("An empty response is not evidence of an
idle queue"); this makes it impossible to get wrong.

Standalone by design
--------------------
The deploy that caused #1179 was a plain ``docker compose up -d api gateway``
against ``/root/.syntropic137/docker-compose.syntropic137.yaml`` on a VPS that
has no repo checkout, no ``just`` and no ``uv``. A check that only runs from a
repo would not have been present where the incident happened. This module
therefore imports nothing but the standard library and nothing from this repo,
so it can be copied to such a host and run with a bare ``python3``. That
property is enforced by ``test_predeploy_check.py``; keep it.

Configuration (same env vars as the ``syn`` CLI, so operators configure once):

    SYN_API_URL       base URL, default http://localhost:8137
    SYN_API_TOKEN     bearer token, or
    SYN_API_USER      basic-auth user, default "admin" (the gateway's own
                      default in infra/docker/images/gateway/docker-entrypoint.sh)
    SYN_API_PASSWORD  basic-auth password
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# Duplicated rather than imported so this file stays copyable to a host with no
# repo (see "Standalone by design"). Sources of truth:
#   DEFAULT_API_URL -> syn_shared.settings.constants.DEFAULT_SELFHOST_API_URL
#   API_PREFIX      -> infra/docker/images/gateway/docker-entrypoint.sh
DEFAULT_API_URL = "http://localhost:8137"
API_PREFIX = "/api/v1"

#: The API caps ``page_size`` at 100, so more than one request may be needed.
PAGE_SIZE = 100

#: Bound the paging loop; 5000 running executions is not a real deployment.
MAX_PAGES = 50

EXIT_CLEAR = 0
EXIT_IN_FLIGHT = 1
EXIT_UNAVAILABLE = 2


class DrainCheckUnavailable(RuntimeError):
    """The check could not determine what is in flight.

    Deliberately distinct from "nothing is in flight". Callers must not treat
    this as an all-clear -- see the module docstring.
    """


@dataclass(frozen=True)
class RunningExecution:
    """One execution a deploy would orphan, with enough to judge the cost."""

    execution_id: str
    workflow_name: str
    phase: str
    """Name of the phase currently running, or ``"unknown"`` if the detail
    lookup failed. Descriptive only -- never affects whether we block."""
    running_for: str
    """Human-readable duration, formatted by the API so every client agrees."""


def running_executions(
    base_url: str,
    *,
    auth_header: str | None = None,
    timeout: float = 15.0,
) -> list[RunningExecution]:
    """Return every execution the API reports as running.

    An empty list means the API was reached and reported nothing running. Any
    failure to establish that -- connection refused, non-200, unparseable body
    -- raises :class:`DrainCheckUnavailable` instead of returning a count.

    Resolving each execution's current phase needs a second request, and that
    one is allowed to fail: by then we already know the execution is running,
    which is the safety-critical fact. A failed lookup degrades the reported
    phase to ``"unknown"`` and never removes the execution from the list.
    """
    url = f"{base_url.rstrip('/')}{API_PREFIX}"
    collected: dict[str, RunningExecution] = {}

    for page in range(1, MAX_PAGES + 1):
        body = _get_json(
            f"{url}/executions?status=running&page={page}&page_size={PAGE_SIZE}",
            auth_header=auth_header,
            timeout=timeout,
        )
        summaries = body.get("executions")
        if not isinstance(summaries, list):
            raise DrainCheckUnavailable(
                f"{url}/executions returned no 'executions' list -- cannot tell what is running"
            )
        for summary in summaries:
            if not isinstance(summary, dict):
                # Skipping it would under-count, which is the failure mode this
                # whole module exists to prevent. We cannot read the list.
                raise DrainCheckUnavailable(
                    f"{url}/executions returned a non-object entry -- cannot tell what is running"
                )
            execution_id = str(summary.get("workflow_execution_id") or "unknown")
            collected[execution_id] = RunningExecution(
                execution_id=execution_id,
                workflow_name=str(summary.get("workflow_name") or "unknown"),
                phase=_running_phase(url, execution_id, auth_header, timeout),
                running_for=str(summary.get("duration_display") or "unknown"),
            )
        # A short page is the last page. Executions completing mid-scan shift
        # the offsets, which is why results are keyed by id.
        if len(summaries) < PAGE_SIZE:
            break

    return list(collected.values())


def _running_phase(url: str, execution_id: str, auth_header: str | None, timeout: float) -> str:
    """Name the phase currently running, or ``"unknown"`` if it cannot be read."""
    try:
        detail = _get_json(
            f"{url}/executions/{execution_id}", auth_header=auth_header, timeout=timeout
        )
    except DrainCheckUnavailable:
        return "unknown"
    phases = detail.get("phases")
    if not isinstance(phases, list):
        return "unknown"
    for phase in phases:
        if isinstance(phase, dict) and phase.get("status") == "running":
            return str(phase.get("name") or "unknown")
    return "unknown"


def _get_json(url: str, *, auth_header: str | None, timeout: float) -> dict[str, object]:
    """GET a JSON object, translating every failure into DrainCheckUnavailable."""
    request = urllib.request.Request(url, method="GET")
    if auth_header:
        request.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise DrainCheckUnavailable(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DrainCheckUnavailable(f"cannot reach {url}: {exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise DrainCheckUnavailable(f"unreadable response from {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DrainCheckUnavailable(f"{url} returned {type(payload).__name__}, not an object")
    return payload


def auth_header_from_env(env: Mapping[str, str] | None = None) -> str | None:
    """Build an Authorization header from the same env vars the CLI reads."""
    source = os.environ if env is None else env
    token = source.get("SYN_API_TOKEN")
    if token:
        return f"Bearer {token}"
    password = source.get("SYN_API_PASSWORD")
    if password:
        user = source.get("SYN_API_USER") or "admin"
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        return f"Basic {encoded}"
    return None


def _report(executions: list[RunningExecution], *, force: bool) -> int:
    """Print the verdict and return the exit code that goes with it."""
    if not executions:
        print("✅ Nothing in flight. Safe to deploy.")
        return EXIT_CLEAR

    print(f"⛔ {len(executions)} execution(s) in flight — deploying now would orphan them.")
    print()
    print(f"  {'EXECUTION':<22} {'RUNNING FOR':<12} {'PHASE':<28} WORKFLOW")
    for execution in executions:
        print(
            f"  {execution.execution_id:<22} {execution.running_for:<12} "
            f"{execution.phase:<28} {execution.workflow_name}"
        )
    print()

    if force:
        print(
            f"⚠️  --force: PROCEEDING ANYWAY. These {len(executions)} execution(s) "
            "will be orphaned\n"
            "    and their work discarded. Any pull request they already opened "
            "will be left\n"
            "    open and unverified."
        )
        return EXIT_CLEAR

    print("Wait for these to finish, or re-run with --force to deploy anyway.")
    return EXIT_IN_FLIGHT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse to deploy while agent executions are in flight (#1179).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  nothing running (or --force)
  1  executions in flight
  2  could not determine — never reported as "nothing running"
        """,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Deploy anyway, orphaning whatever is running. Says so loudly.",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SYN_API_URL") or DEFAULT_API_URL,
        help=f"API base URL (default: $SYN_API_URL, else {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--timeout", type=float, default=15.0, help="Per-request timeout in seconds"
    )
    args = parser.parse_args(argv)

    try:
        executions = running_executions(
            args.api_url,
            auth_header=auth_header_from_env(),
            timeout=args.timeout,
        )
    except DrainCheckUnavailable as exc:
        print(f"❌ Cannot determine what is running: {exc}", file=sys.stderr)
        print(
            "   This is NOT an all-clear. The API being unreachable is exactly\n"
            "   when executions are most likely still in flight.",
            file=sys.stderr,
        )
        if args.force:
            print(
                "⚠️  --force: PROCEEDING ANYWAY without knowing what is running.",
                file=sys.stderr,
            )
            return EXIT_CLEAR
        print(
            "   Fix connectivity (SYN_API_URL / SYN_API_TOKEN / SYN_API_PASSWORD),\n"
            "   or re-run with --force to deploy blind.",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE

    return _report(executions, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
