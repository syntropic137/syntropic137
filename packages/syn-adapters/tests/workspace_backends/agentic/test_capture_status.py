"""Capture-outcome parsing, against the finalizer's real output strings.

Fixtures are copied from
lib/agentic-primitives/workspace/capabilities/session-store/seshmagic/finalize.sh
rather than invented, because a parser tested against strings the author of the
parser made up tests only that the author is self-consistent.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_adapters.workspace_backends.agentic.capture_status import (
    CaptureState,
    parse_capture_status,
)

# Real lines, with the entrypoint noise that surrounds them in a live container.
_NOISE = (
    "[entrypoint] Discovered plugin: delegation\n[entrypoint] Discovered plugin: observability\n"
)
_OK = _NOISE + "[finalize] session-store upload complete (discovered=2 uploaded=2 accepted=2);\n"
_TIMEOUT = _NOISE + "[finalize] session-store upload TIMED OUT after 2s; spool retained\n"
_FAILED = _NOISE + "[finalize] session-store upload FAILED (rc=9); spool retained\n"
_INCOMPLETE = (
    _NOISE + "[finalize] session-store sweep INCOMPLETE (failed=1): at least one transcript\n"
)
_UNPARSEABLE = (
    _NOISE + "[finalize] session-store sweep produced no parseable summary line; treating\n"
)


@pytest.mark.unit
class TestCaptureStatesAreDistinguishable:
    """Collapsing these to a boolean is how an operator loses the ability to
    tell a store outage from a misconfiguration from a run with nothing to send.
    """

    def test_no_store_configured_is_disabled_not_a_failure(self) -> None:
        assert parse_capture_status("", store_enabled=False).state is CaptureState.DISABLED

    def test_clean_sweep_is_captured(self) -> None:
        out = parse_capture_status(_OK, store_enabled=True)
        assert out.state is CaptureState.CAPTURED
        assert out.reason is None

    def test_timeout_is_failed_and_says_how_long(self) -> None:
        out = parse_capture_status(_TIMEOUT, store_enabled=True)
        assert out.state is CaptureState.FAILED
        assert "2s" in (out.reason or "")

    def test_nonzero_exit_is_failed_and_carries_the_code(self) -> None:
        out = parse_capture_status(_FAILED, store_enabled=True)
        assert out.state is CaptureState.FAILED
        assert "9" in (out.reason or "")

    def test_incomplete_sweep_is_distinct_from_failure(self) -> None:
        # The exporter WORKED; the store or a transcript was the problem, so
        # retrying the same call unchanged will usually repeat it.
        out = parse_capture_status(_INCOMPLETE, store_enabled=True)
        assert out.state is CaptureState.INCOMPLETE
        assert "failed=1" in (out.reason or "")


@pytest.mark.unit
class TestUnknownIsNeverOptimistic:
    """An unrecognised line means the finalizer changed and this parser did not.
    Surfacing that is the point; assuming success would hide it forever.
    """

    def test_store_enabled_but_finalizer_silent_is_unknown(self) -> None:
        out = parse_capture_status(_NOISE, store_enabled=True)
        assert out.state is CaptureState.UNKNOWN
        assert "emitted nothing" in (out.reason or "")

    def test_unparseable_summary_is_unknown_not_captured(self) -> None:
        assert parse_capture_status(_UNPARSEABLE, store_enabled=True).state is CaptureState.UNKNOWN

    def test_unrecognised_finalizer_line_is_unknown(self) -> None:
        weird = "[finalize] session-store did something nobody has written a branch for\n"
        assert parse_capture_status(weird, store_enabled=True).state is CaptureState.UNKNOWN


@pytest.mark.unit
class TestBackfillTargeting:
    """needs_backfill decides what a recovery pass re-sends, so its bias matters.

    Re-sending an already-stored session is a no-op (the store dedups on
    content_hash); skipping one is a permanently lost transcript. The costs are
    not symmetric, so uncertainty must resolve toward re-sending.
    """

    def test_captured_needs_nothing(self) -> None:
        assert not parse_capture_status(_OK, store_enabled=True).needs_backfill

    def test_disabled_needs_nothing(self) -> None:
        assert not parse_capture_status("", store_enabled=False).needs_backfill

    @pytest.mark.parametrize("stderr", [_TIMEOUT, _FAILED, _INCOMPLETE, _UNPARSEABLE, _NOISE])
    def test_every_non_success_state_is_a_backfill_candidate(self, stderr: str) -> None:
        assert parse_capture_status(stderr, store_enabled=True).needs_backfill


@pytest.mark.unit
class TestCountersAndSafety:
    def test_counters_are_recovered_when_present(self) -> None:
        out = parse_capture_status(_OK, store_enabled=True)
        assert out.counters == {"discovered": 2, "uploaded": 2, "accepted": 2}

    def test_outcome_is_immutable(self) -> None:
        out = parse_capture_status(_OK, store_enabled=True)
        with pytest.raises(ValidationError):
            out.state = CaptureState.FAILED  # type: ignore[misc]

    def test_a_credential_in_the_stream_never_reaches_the_reason(self) -> None:
        # The finalizer withholds the exporter's own output precisely so a
        # binary that prints an auth header cannot leak it. If something does
        # appear on the stream, this parser must not lift it into a field that
        # gets stored and displayed.
        leaked = (
            "Authorization: Bearer sk-super-secret-value\n"
            "[finalize] session-store upload FAILED (rc=1); spool retained\n"
        )
        out = parse_capture_status(leaked, store_enabled=True)
        assert "sk-super-secret-value" not in (out.reason or "")
        assert "sk-super-secret-value" not in str(out.counters)


@pytest.mark.unit
class TestCaptureIsTelemetryNotDomainState:
    """Capture belongs on Lane 2 (observability), never Lane 1 (event sourcing).

    Whether a transcript reached the central store has no bearing on whether the
    workflow succeeded, and must never acquire one. If a failed upload could
    fail an execution, the fail-open policy would be silently reversed by the
    back door.
    """

    def test_there_is_an_observation_type_for_it(self) -> None:
        from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
            ObservationType,
        )

        assert ObservationType.SESSION_CAPTURE.value == "session_capture"

    def test_every_state_is_representable_as_observation_data(self) -> None:
        # The outcome has to survive the trip through record_observation, which
        # takes a plain dict. A state that cannot round-trip would be recorded
        # as something else, and a wrong record is worse than none.
        for stderr, enabled in [
            (_OK, True),
            (_FAILED, True),
            (_INCOMPLETE, True),
            (_UNPARSEABLE, True),
            ("", False),
        ]:
            out = parse_capture_status(stderr, store_enabled=enabled)
            data = out.model_dump(mode="json")
            assert data["state"] == out.state.value
            assert set(data) == {"state", "reason", "counters"}


@pytest.mark.unit
class TestTheWritePathAcceptsWhatTheDomainProduces:
    """An ObservationType the write path rejects is a recording that raises.

    The existing event-type consistency test checks agentic_events (the hook
    producer) against syn_shared. It does NOT check syn-domain's ObservationType,
    which is a separate producer, so SESSION_CAPTURE was added to the domain enum
    and silently absent from VALID_EVENT_TYPES - accepted by the type checker,
    rejected at the moment of writing.

    That failure is worse here than elsewhere: capture is fail-open, and an
    exception on the recording path would fail an execution over a telemetry
    write, reversing the policy by accident.
    """

    def test_session_capture_is_accepted_by_the_write_path(self) -> None:
        from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
            ObservationType,
        )
        from syn_shared.events import is_valid_event_type

        assert is_valid_event_type(ObservationType.SESSION_CAPTURE.value)

    #: ObservationType values the write path would reject TODAY. Pre-existing,
    #: and latent rather than live: four have no production caller at all and
    #: PROGRESS has one. Pinned as a ratchet rather than fixed here, because
    #: adding five types to the write-path Literal on the way past is a change
    #: to what the collector accepts, and that deserves its own reasoning rather
    #: than riding along in a capture-indicator PR.
    KNOWN_UNWRITABLE = frozenset(
        {"cancelled", "completed", "execution_stopped", "progress", "started"}
    )

    def test_no_new_observation_type_is_unwritable(self) -> None:
        # The general form, as a ratchet. A NEW ObservationType added without a
        # matching EventType entry fails here rather than at the first write
        # attempt, which is the failure this class was written after making.
        from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
            ObservationType,
        )
        from syn_shared.events import VALID_EVENT_TYPES

        unwritable = {t.value for t in ObservationType if t.value not in VALID_EVENT_TYPES}
        new = sorted(unwritable - self.KNOWN_UNWRITABLE)
        assert not new, (
            f"ObservationType value(s) the write path would reject: {new}. "
            f"Add them to syn_shared.events.EventType, or a record_observation "
            f"call with one will raise at the moment of writing."
        )

    def test_the_ratchet_shrinks_and_never_grows(self) -> None:
        # If someone fixes one of the known five, this fails and tells them to
        # tighten the pin. A ratchet that only ever gets looser is a comment.
        from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
            ObservationType,
        )
        from syn_shared.events import VALID_EVENT_TYPES

        unwritable = {t.value for t in ObservationType if t.value not in VALID_EVENT_TYPES}
        fixed = sorted(self.KNOWN_UNWRITABLE - unwritable)
        assert not fixed, f"these are writable now; remove them from KNOWN_UNWRITABLE: {fixed}"


@pytest.mark.unit
class TestTheStreamIsUntrusted:
    """The agent and the finalizer share one stderr, and the agent is a model
    that can be induced to print anything. These pin what that does and does not
    let it do.
    """

    def test_prose_merely_mentioning_the_phrase_does_not_count_as_success(self) -> None:
        # Unanchored matching classified this as CAPTURED. An agent narrating
        # what it was doing could therefore fake a successful capture by
        # accident, with no finalizer involved at all.
        chatter = (
            "I checked whether the [finalize] session-store upload complete "
            "message had appeared, and it had not.\n"
        )
        assert parse_capture_status(chatter, store_enabled=True).state is CaptureState.UNKNOWN

    def test_a_credential_inside_a_matching_incomplete_line_is_not_stored(self) -> None:
        # The earlier safety test put the secret on its own line ahead of a
        # FAILED verdict, so it never exercised the capture group that copied
        # parenthesised text straight into `reason`. This is that path.
        leaked = (
            "[finalize] session-store sweep INCOMPLETE "
            "(failed=1 Authorization: Bearer sk-inside-the-capture-group): at least one\n"
        )
        out = parse_capture_status(leaked, store_enabled=True)
        assert out.state is CaptureState.INCOMPLETE
        assert "sk-inside-the-capture-group" not in (out.reason or "")
        assert "Bearer" not in (out.reason or "")
        # It still says something useful, rebuilt from whitelisted fields.
        assert "failed=1" in (out.reason or "")

    def test_counters_come_from_the_verdict_line_not_from_earlier_output(self) -> None:
        # Searching the whole stream took the FIRST match, so unrelated earlier
        # output silently displaced the real numbers.
        noisy = (
            "the agent printed accepted=999 while reasoning about something else\n"
            "[finalize] session-store upload complete (discovered=1 uploaded=1 accepted=1);\n"
        )
        out = parse_capture_status(noisy, store_enabled=True)
        assert out.state is CaptureState.CAPTURED
        assert out.counters["accepted"] == 1, "the verdict line's own counter must win"

    def test_the_two_counters_that_explain_a_non_delivery_are_read(self) -> None:
        # rejected and skipped_oversize were missing from the whitelist. They
        # are what distinguish "the store refused it" from "we never sent it".
        line = (
            "[finalize] session-store sweep INCOMPLETE "
            "(rejected=2 skipped_oversize=1): at least one transcript\n"
        )
        out = parse_capture_status(line, store_enabled=True)
        assert out.counters["rejected"] == 2
        assert out.counters["skipped_oversize"] == 1

    def test_a_verbatim_forged_success_line_IS_currently_believed(self) -> None:
        """Documents a real limitation as an ASSERTION rather than an xfail.

        An agent that emits the finalizer's success line verbatim is believed.
        Anchoring raised this from accidental to deliberate; it is not a trust
        boundary, and pretending otherwise would be worse than saying so.

        Written as a passing test on purpose. An xfail here would be a disarmed
        alarm - this repo's own fitness gate says so - whereas this asserts what
        the code actually does today and FAILS THE DAY SOMEONE FIXES IT, which
        is the moment the fixer should be told to update this test and the
        module's trust note.

        The fix is a channel the agent cannot write to: the finalizer writing
        its result to a file under the host-backed workspace directory, which
        Syn137 already collects into MinIO. Then this parser becomes a fallback
        for older images rather than the source of truth.
        """
        forged = "[finalize] session-store upload complete (uploaded=1 accepted=1);\n"
        assert parse_capture_status(forged, store_enabled=True).state is CaptureState.CAPTURED, (
            "If this now fails, the forgery gap has been closed. Good. Update "
            "this test to assert the new behaviour and drop the trust caveat "
            "from capture_status.py's module docstring."
        )
