"""The reason texts codex's own failures are reported under.

Split out of ``CodexStreamProcessor`` (#1825) so the stream processor stays a
stream processor: the spellings codex's failures are reported under, and the
stdout login-fault filter that produces one of them. What KIND of fault each
is, is agentic-workspace's classifier's call (#1605), not this module's.
"""

from __future__ import annotations

import re

from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    api_error_label,
)

# --- Terminal faults the codex CLI reports on stdout as NON-JSON log lines ----
#
# The codex CLI writes tracing lines to the same stdout as its JSON events. Most
# are inert noise (see module docstring) and are rightly discarded, but a login
# failure is announced ONLY there:
#
#   ERROR codex_login::auth::manager: Failed to refresh token: 401 Unauthorized
#   ... "code": "refresh_token_reused"
#
# Discarding it meant an expired codex login surfaced downstream as "codex
# stream ended without a terminal turn.completed event" - a true statement
# about a symptom that names the wrong subsystem and gives an operator nothing
# to act on (issue #891).
#
# THREE conditions, ALL required. Each rejects lines the other two accept.
#
#   1. error severity, ANCHORED to the tracing-line format,
#   2. auth CONTEXT (the codex_login target, or an auth:: module path),
#   3. an explicit auth-FAILURE marker.
#
# Why each is needed, with the line that motivates it:
#
# (1) anchored severity. A severity word can appear anywhere in a line,
#     including inside captured command output:
#
#       INFO codex_exec: command output: ERROR deleting file: unauthorized operation
#
#     A file-deletion failure is not an auth failure. Matching `ERROR`
#     anywhere would diagnose it as one. The tracing format puts the severity
#     first, so that is where it is required.
#
# (2) auth context. The golden fixture carries a routine
#     `ERROR codex_models_manager::manager: ...` diagnostic; without an auth
#     requirement, a severity+marker filter would promote unrelated subsystem
#     errors into authentication verdicts.
#
# (3) a failure marker. The subsystem NAME is not evidence of a fault -
#     healthy lines carry it too:
#
#       INFO codex_login::auth::manager: loaded cached credentials
#
#     An early draft ORed its alternatives, so the bare name matched. Because
#     AgentExecutionHandler forces exit code 1 whenever a codex stream carries
#     any error_reason, that draft would have failed SUCCESSFUL codex phases -
#     a worse defect than the missing reason it set out to fix.
#
# The marker list is deliberately broader than the single production line that
# prompted #891. Real auth failures the CLI spells differently -
# "Authentication failed: HTTP 401", "token expired" - were falling through to
# the generic "stream ended without a terminal turn" message, which is exactly
# the misdiagnosis this exists to remove.
_TRACING_ERROR_SEVERITY_RE = re.compile(r"^\s*(?:ERROR|FATAL)\b")
_AUTH_CONTEXT_RE = re.compile(r"codex_login|auth::", re.IGNORECASE)
_AUTH_FAILURE_MARKER_RE = re.compile(
    r"failed to refresh token"
    r"|refresh_token_reused"
    r"|invalid_grant"
    r"|unauthorized"
    r"|authentication failed"
    r"|token expired"
    r"|login required"
    r"|\b(?:401|403)\b",
    re.IGNORECASE,
)
_HTTP_AUTH_STATUS_RE = re.compile(r"\b(401|403)\b")
_MAX_FAULT_LINE_LEN = 160


def codex_fault_reason(message: str) -> str:
    """The reason text codex's own words about a failed turn are reported under.

    A function rather than an f-string at the one call site because it is not
    only written here: the upstream failure reader knows a reason is codex's
    by the prefix this writes with an empty message. Two copies of that prefix
    would drift the first time either changed, and the failure would be
    silent - codex's faults read as claude's, and a busy codex never retried.
    """
    return f"codex reported: {message[:_MAX_FAULT_LINE_LEN]}"


def codex_login_fault_reason(status: str, line: str) -> str:
    """The reason text a codex CLI login fault on stdout is reported under.

    Spelled with claude's auth label, so agentic-workspace's claude
    classifier, which reads every reason not on codex's fault line, reads
    it as `auth` (#1605).
    """
    label = api_error_label(ApiErrorType.AUTHENTICATION, status)
    return f"{label}: codex CLI login - {line[:_MAX_FAULT_LINE_LEN]}"


def codex_login_fault_in(line: str) -> str | None:
    """The login-fault reason a non-JSON stdout line carries, or ``None``.

    All three conditions above are required; see there for why each is.
    """
    if not _TRACING_ERROR_SEVERITY_RE.search(line):
        return None
    if not _AUTH_CONTEXT_RE.search(line):
        return None
    if not _AUTH_FAILURE_MARKER_RE.search(line):
        return None
    status = _HTTP_AUTH_STATUS_RE.search(line)
    return codex_login_fault_reason(status.group(1) if status else "", line)


# --- The workspace ran out of processes (#2227) --------------------------------
#
# A workspace container has a pids limit (`resources.pids_limit`, default 256).
# When the agent's commands use it up, the next process cannot start (EAGAIN)
# and bash says so in the command's output:
#
#   /usr/bin/bash: fork: retry: Resource temporarily unavailable
#   /usr/bin/bash: fork: Resource temporarily unavailable
#
# Codex itself then cannot start processes either, and its stream stops without
# `turn.completed`. Reported as the generic "stream ended" reason, that cost an
# operator the cause: exec-f02a26a13856 read as a codex fault for a verify phase
# that had simply run two parallel builds into the limit.
#
# Anchored to bash's two spellings, not to EAGAIN's text alone: "Resource
# temporarily unavailable" is also what a non-blocking read says when it has
# nothing to read, which is not a fault at all. They are spelled out whole
# because the orchestration context reserves the bare word for an execution
# operation (ci/fitness/code_quality/test_reserved_domain_words.py), and only
# these exact process-limit messages are exempt from that gate.
_BASH_OUT_OF_PIDS = (
    "fork: retry: Resource temporarily unavailable",
    "fork: Resource temporarily unavailable",
)
_OUT_OF_PIDS_RE = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, _BASH_OUT_OF_PIDS)) + ")")


def codex_pids_fault_in(output: str, pids_limit: int | None) -> str | None:
    """The pids-exhaustion reason a command's output carries, or ``None``.

    ``pids_limit`` is the limit the workspace was provisioned with, named in the
    reason because raising it is the fix; None when nobody recorded it.

    A REAL fault, deliberately not a refinement of the "stream ended" reason:
    a phase that ends on it is neither retried (#1335, the same limit hits the
    same wall) nor completed on its deliverable (#1111, the commands it
    depended on could not run).
    """
    if not _OUT_OF_PIDS_RE.search(output):
        return None
    limit = "" if pids_limit is None else f" ({pids_limit})"
    return (
        f"workspace hit its pids limit{limit}: bash could not start a process "
        "(`fork: Resource temporarily unavailable`); raise the phase's resources.pids_limit"
    )
