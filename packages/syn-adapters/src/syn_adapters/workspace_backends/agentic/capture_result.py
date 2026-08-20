"""Parse the exporter's own machine-readable result.

WHY THIS EXISTS ALONGSIDE `capture_status`. That module reads the finalizer's
stderr, which is the DIAGNOSTIC path: the agent and the finalizer run as the
same Unix user inside the workspace, so anything the finalizer prints the agent
can print too. A success line read from there is evidence, never proof, and
recording it as proof would be worse than recording nothing - a confident wrong
answer about whether a session survived.

This module reads `apss-session-exporter --json`, invoked BY THE HOST over a
channel the agent has no handle on. That is what makes the verdict
authoritative. The two are deliberately separate rather than one parser with a
flag, because the difference between them is trust, and a shared entry point
would make it easy to forget which one you are holding.

The exporter's contract (agentic-session-exporter >= 0.3.0):

    exit 0  every session found reached the store, was already there, or was
            unchanged
    exit 3  the sweep RAN but did not capture everything it found
    exit 1  the sweep could not run at all
    exit 2  usage error

and `--json` prints exactly one object on stdout, versioned, with the counters
plus the store URL and resolved origin. The origin matters as much as the
counters: an exporter pointed at the WRONG store reports identical numbers to
one pointed at the right one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from syn_adapters.workspace_backends.agentic.capture_status import CaptureState

__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "AuthoritativeCapture",
    "parse_capture_result",
]

#: The `schema_version` this parser understands. The exporter bumps it on any
#: incompatible change precisely so a consumer can refuse a shape it does not
#: know instead of misreading it, which is what this constant is for.
SUPPORTED_SCHEMA_VERSION: Final = 1

#: Exit codes the exporter defines. Named rather than inlined so the mapping
#: below reads as the contract it implements.
_EXIT_CAPTURED: Final = 0
_EXIT_COULD_NOT_RUN: Final = 1
_EXIT_USAGE: Final = 2
_EXIT_INCOMPLETE: Final = 3


class AuthoritativeCapture(BaseModel):
    """A capture verdict obtained over a channel the agent cannot write to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: CaptureState
    reason: str | None = None
    #: Where the sessions went. Recorded because identical counters from the
    #: wrong store look exactly like the right ones.
    store_url: str | None = None
    origin_environment: str | None = None
    origin_deployment: str | None = None
    counters: dict[str, int] = Field(default_factory=dict)

    @property
    def needs_backfill(self) -> bool:
        """True when a later pass should try this execution's sessions again.

        Biased toward re-sending. The store deduplicates on content hash, so a
        redundant re-send costs a request; a missed one costs a transcript that
        nothing downstream can notice is absent.
        """
        return self.state in (
            CaptureState.INCOMPLETE,
            CaptureState.FAILED,
            CaptureState.UNKNOWN,
        )


def _unknown(reason: str, counters: dict[str, int] | None = None) -> AuthoritativeCapture:
    return AuthoritativeCapture(state=CaptureState.UNKNOWN, reason=reason, counters=counters or {})


def parse_capture_result(
    stdout: str,
    exit_code: int,
    *,
    store_enabled: bool,
    expected_store_url: str | None,
    expected_deployment: str | None,
) -> AuthoritativeCapture:
    """Interpret one host-invoked exporter run.

    Args:
        stdout: The process's stdout. Under `--json` this is exactly one JSON
            object; the exporter routes its logs to stderr precisely so this
            stream stays parseable.
        exit_code: The process's exit status.
        store_enabled: Whether a store is configured at all.

    Split into a guard pass and a verdict pass. The guards answer "can this
    result be read at all", and every one of them returns a verdict that is NOT
    a success, so nothing below them has to re-check whether it is looking at
    something trustworthy.

    `expected_store_url` and `expected_deployment` have NO DEFAULT on purpose,
    though None is a permitted value. A caller that omits them would otherwise
    get the permissive behaviour by forgetting, and "the safe path depends on
    remembering something" is the shape of defect this module exists to remove.
    Passing None is a decision a reader can see; omitting the argument is not.
    """
    document = _load_document(stdout)
    refusal = _refuse_unreadable(document, exit_code, store_enabled=store_enabled)
    if refusal is not None:
        return refusal

    # _refuse_unreadable returns non-None for every document it rejects,
    # including None itself, so anything reaching here is a readable mapping.
    return _verdict(
        document or {},
        exit_code,
        expected_store_url=expected_store_url,
        expected_deployment=expected_deployment,
    )


def _refuse_unreadable(
    document: Mapping[str, object] | None,
    exit_code: int,
    *,
    store_enabled: bool,
) -> AuthoritativeCapture | None:
    """Everything that makes a result unreadable, or trivially not a capture.

    Returns None when the document is worth interpreting. Never returns
    CAPTURED: a guard that could report success would defeat its own purpose.
    """
    if not store_enabled:
        return AuthoritativeCapture(
            state=CaptureState.DISABLED, reason="no session store configured"
        )

    if exit_code == _EXIT_USAGE:
        # The host built the command line, so this is our bug, not the store's.
        return _unknown(f"exporter rejected its arguments (exit {exit_code})")

    if document is None:
        # The exit code alone is not enough: exit 0 without a document means the
        # binary is older than --json, which is a configuration problem rather
        # than a capture success.
        return _unknown(
            f"exporter produced no parseable JSON result (exit {exit_code}); "
            "the binary may predate --json"
        )

    version = document.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        return _unknown(
            f"exporter result schema_version {version!r} is not "
            f"{SUPPORTED_SCHEMA_VERSION}; refusing to guess at its meaning"
        )

    if not isinstance(document.get("captured_everything"), bool):
        return _unknown(
            "exporter result has no boolean captured_everything",
            counters=_counters(document),
        )

    return None


def _verdict(
    document: Mapping[str, object],
    exit_code: int,
    *,
    expected_store_url: str | None,
    expected_deployment: str | None,
) -> AuthoritativeCapture:
    """Turn a readable document plus its exit code into a verdict."""
    counters = _counters(document)
    raw_origin = document.get("origin")
    origin: Mapping[str, object] = raw_origin if isinstance(raw_origin, Mapping) else {}
    captured_everything = bool(document.get("captured_everything"))

    store_url = _text(document.get("store_url"))
    origin_deployment = _text(origin.get("deployment"))
    fields = {
        "store_url": store_url,
        "origin_environment": _text(origin.get("environment")),
        "origin_deployment": origin_deployment,
        "counters": counters,
    }

    if exit_code == _EXIT_COULD_NOT_RUN:
        return AuthoritativeCapture(
            state=CaptureState.FAILED,
            reason=_text(document.get("error")) or "the sweep could not run",
            **fields,  # type: ignore[arg-type]
        )

    # Cross-check. Both come from the same process, so a disagreement means the
    # exporter or the invocation is broken, and neither answer can be trusted
    # afterwards. Preferring whichever says what we want is exactly how a false
    # verdict gets recorded.
    expected_exit = _EXIT_CAPTURED if captured_everything else _EXIT_INCOMPLETE
    if exit_code != expected_exit:
        return AuthoritativeCapture(
            state=CaptureState.UNKNOWN,
            reason=(
                f"exporter exit {exit_code} contradicts captured_everything={captured_everything}"
            ),
            **fields,  # type: ignore[arg-type]
        )

    if captured_everything:
        state, reason = _judge_claimed_success(
            counters,
            store_url=store_url,
            origin_deployment=origin_deployment,
            expected_store_url=expected_store_url,
            expected_deployment=expected_deployment,
        )
        return AuthoritativeCapture(state=state, reason=reason, **fields)  # type: ignore[arg-type]

    lost = {k: v for k, v in counters.items() if k in _LOSS_COUNTERS and v}
    detail = ", ".join(f"{k}={v}" for k, v in sorted(lost.items()))
    return AuthoritativeCapture(
        state=CaptureState.INCOMPLETE,
        reason=f"sweep incomplete ({detail})" if detail else "sweep incomplete",
        **fields,  # type: ignore[arg-type]
    )


def _judge_claimed_success(
    counters: Mapping[str, int],
    *,
    store_url: str | None,
    origin_deployment: str | None,
    expected_store_url: str | None,
    expected_deployment: str | None,
) -> tuple[CaptureState, str | None]:
    """Decide whether a claimed success may be recorded as one."""
    doubt = _doubt_about_success(
        counters,
        store_url=store_url,
        origin_deployment=origin_deployment,
        expected_store_url=expected_store_url,
        expected_deployment=expected_deployment,
    )
    if doubt is not None:
        return CaptureState.UNKNOWN, doubt
    if counters.get("discovered") == 0:
        # Not a failure, but "sessions are in the store" is not true of it
        # either. Recorded so a caller that expected a session can notice,
        # rather than flattened into an indistinguishable success.
        return CaptureState.CAPTURED, "nothing to capture (discovered=0)"
    return CaptureState.CAPTURED, None


def _doubt_about_success(
    counters: Mapping[str, int],
    *,
    store_url: str | None,
    origin_deployment: str | None,
    expected_store_url: str | None,
    expected_deployment: str | None,
) -> str | None:
    """Reasons a claimed success should not be recorded as one.

    CAPTURED is the only state that does NOT set needs_backfill, so it is the
    verdict that decides a session is safe to stop worrying about. Everything
    here exists to make that decision harder to reach by accident.
    """
    # A sweep that succeeded against the WRONG store reports numbers identical
    # to one that succeeded against the right one. The counters cannot tell
    # them apart, and neither can the exit code; only the caller knows where it
    # meant the sessions to go.
    if expected_store_url is not None and store_url != expected_store_url:
        return (
            f"exporter reported success against {store_url!r}, "
            f"not the configured {expected_store_url!r}"
        )
    if expected_deployment is not None and origin_deployment != expected_deployment:
        return (
            f"exporter reported success tagged {origin_deployment!r}, "
            f"not this deployment {expected_deployment!r}"
        )

    # A document claiming success while counting a loss contradicts itself. The
    # v0.3.0 producer cannot emit this, because it derives both the exit code
    # and the boolean FROM these counters. That is exactly why the check is
    # cheap: it costs nothing today and fails closed if the producer ever gains
    # a bug or this parser drifts from it. capture_status.py already refuses
    # the same contradiction on its own path.
    contradicting = {k: v for k, v in counters.items() if k in _LOSS_COUNTERS and v}
    if contradicting:
        named = ", ".join(f"{k}={v}" for k, v in sorted(contradicting.items()))
        return f"exporter claimed success while counting {named}"

    return None


#: Counters whose nonzero value means a session the sweep SAW is not in the
#: store. Mirrors the exporter's own definition of captured_everything.
_LOSS_COUNTERS: Final = ("rejected", "skipped_oversize", "failed", "unconfirmed")


def _load_document(stdout: str) -> Mapping[str, object] | None:
    """The last JSON object on stdout, or None.

    Takes the LAST line rather than the whole stream: a wrapper that prepends
    output is a realistic accident, and being strict about leading noise would
    turn a cosmetic problem into an unreadable verdict.
    """
    for line in reversed([ln.strip() for ln in stdout.splitlines() if ln.strip()]):
        try:
            loaded = json.loads(line)
        except ValueError:
            continue
        if isinstance(loaded, dict):
            return loaded
    return None


def _counters(document: Mapping[str, object]) -> dict[str, int]:
    """Integer counters only. A non-integer is dropped rather than coerced."""
    raw = document.get("counters")
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool)}


def _text(value: object) -> str | None:
    """A non-empty string, or None.

    `object` rather than `Any`: the input genuinely is unknown (it came off the
    wire), and `object` forces the isinstance narrowing below instead of
    letting the value flow anywhere unchecked.
    """
    return value if isinstance(value, str) and value else None
