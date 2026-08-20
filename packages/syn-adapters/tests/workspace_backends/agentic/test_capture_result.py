"""The AUTHORITATIVE capture verdict, as distinct from the diagnostic one.

`capture_status` reads the finalizer's stderr from inside the workspace, where
the agent runs as the same user and can print anything the finalizer can. This
module reads a host-invoked `apss-session-exporter --json`, over a channel the
agent has no handle on. Everything here exists to keep that distinction from
eroding into a confident wrong answer.

The documents below are REAL exporter output, captured from v0.3.0 runs against
a live receiver, not invented shapes. A parser tested against fiction proves
only that it agrees with whoever wrote the fixture.
"""

from __future__ import annotations

import json

import pytest

from syn_adapters.workspace_backends.agentic.capture_result import (
    SUPPORTED_SCHEMA_VERSION,
    parse_capture_result,
)
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState

# Captured from a real v0.3.0 run against a schema-validating receiver.
_CLEAN = json.dumps(
    {
        "schema_version": 1,
        "scs_version": "1.0",
        "captured_everything": True,
        "store_url": "http://host.docker.internal:8799",
        "origin": {"environment": "container", "deployment": "syntropic137__dev"},
        "counters": {
            "discovered": 1,
            "skipped_unchanged": 0,
            "uploaded": 1,
            "accepted": 1,
            "duplicate": 0,
            "rejected": 0,
            "skipped_oversize": 0,
            "failed": 0,
            "unconfirmed": 0,
        },
    }
)

# Captured from a real run against a receiver that rejects every envelope.
_REJECTED = json.dumps(
    {
        "schema_version": 1,
        "scs_version": "1.0",
        "captured_everything": False,
        "store_url": "http://127.0.0.1:8793",
        "origin": {"environment": "container", "deployment": None},
        "counters": {
            "discovered": 1,
            "skipped_unchanged": 0,
            "uploaded": 1,
            "accepted": 0,
            "duplicate": 0,
            "rejected": 1,
            "skipped_oversize": 0,
            "failed": 0,
            "unconfirmed": 0,
        },
    }
)

# Captured from a real run against an unreachable store.
_UNREACHABLE = json.dumps(
    {
        "schema_version": 1,
        "scs_version": "1.0",
        "captured_everything": False,
        "error": "store is not reachable at http://127.0.0.1:1 (is it up? is the URL right?)",
        "store_url": "http://127.0.0.1:1",
        "origin": {"environment": "container", "deployment": "syntropic137__dev"},
    }
)


@pytest.mark.unit
class TestTheThreeRealOutcomes:
    def test_a_clean_sweep_is_captured(self) -> None:
        out = parse_capture_result(_CLEAN, 0, store_enabled=True)
        assert out.state is CaptureState.CAPTURED
        assert not out.needs_backfill
        assert out.origin_deployment == "syntropic137__dev"
        assert out.store_url == "http://host.docker.internal:8799"

    def test_a_rejected_sweep_is_incomplete_and_names_the_loss(self) -> None:
        out = parse_capture_result(_REJECTED, 3, store_enabled=True)
        assert out.state is CaptureState.INCOMPLETE
        assert out.needs_backfill
        assert "rejected=1" in (out.reason or "")

    def test_an_unreachable_store_is_failed_and_carries_the_error(self) -> None:
        out = parse_capture_result(_UNREACHABLE, 1, store_enabled=True)
        assert out.state is CaptureState.FAILED
        assert out.needs_backfill
        assert "not reachable" in (out.reason or "")


@pytest.mark.unit
class TestTheVerdictIsNeverGuessed:
    def test_a_disabled_store_is_not_a_failure(self) -> None:
        out = parse_capture_result("", 0, store_enabled=False)
        assert out.state is CaptureState.DISABLED
        assert not out.needs_backfill

    def test_an_unknown_schema_version_is_refused(self) -> None:
        # The exporter bumps this on any incompatible change precisely so a
        # consumer can refuse rather than misread. Guessing would mean reading
        # a field that may have changed meaning.
        doc = json.dumps(
            {"schema_version": SUPPORTED_SCHEMA_VERSION + 1, "captured_everything": True}
        )
        out = parse_capture_result(doc, 0, store_enabled=True)
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill

    def test_no_document_is_not_success(self) -> None:
        # An exporter older than --json exits 0 and prints a prose line. That
        # is a misconfiguration, not a capture, and must never read as one.
        out = parse_capture_result(
            "run: discovered=1 uploaded=1 accepted=1 failed=0", 0, store_enabled=True
        )
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill
        assert "predate" in (out.reason or "")

    def test_exit_code_contradicting_the_document_is_unknown(self) -> None:
        # Both come from the same process. If they disagree, something is wrong
        # with the exporter or the invocation, and preferring whichever says
        # what we want is exactly how a false verdict gets recorded.
        out = parse_capture_result(_CLEAN, 3, store_enabled=True)
        assert out.state is CaptureState.UNKNOWN
        assert "contradicts" in (out.reason or "")

    def test_a_usage_error_is_our_bug_not_the_stores(self) -> None:
        out = parse_capture_result("", 2, store_enabled=True)
        assert out.state is CaptureState.UNKNOWN
        assert "arguments" in (out.reason or "")

    def test_a_missing_captured_everything_is_unknown(self) -> None:
        doc = json.dumps({"schema_version": 1, "counters": {"failed": 0}})
        out = parse_capture_result(doc, 0, store_enabled=True)
        assert out.state is CaptureState.UNKNOWN


@pytest.mark.unit
class TestParsingIsDefensive:
    def test_leading_noise_does_not_break_the_verdict(self) -> None:
        # A wrapper prepending output is a realistic accident. Being strict
        # about it would turn a cosmetic problem into an unreadable verdict.
        out = parse_capture_result(f"some wrapper noise\n{_CLEAN}", 0, store_enabled=True)
        assert out.state is CaptureState.CAPTURED

    def test_non_integer_counters_are_dropped_not_coerced(self) -> None:
        doc = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "counters": {"uploaded": 1, "accepted": "one", "failed": True},
            }
        )
        out = parse_capture_result(doc, 0, store_enabled=True)
        assert out.counters == {"uploaded": 1}, out.counters

    def test_garbage_is_unknown_rather_than_an_exception(self) -> None:
        out = parse_capture_result("{not json at all", 0, store_enabled=True)
        assert out.state is CaptureState.UNKNOWN


# What the exporter emits when it cannot even load its configuration: the same
# envelope, with store_url and origin explicitly null rather than invented.
_CONFIG_ERROR = json.dumps(
    {
        "schema_version": 1,
        "scs_version": "1.0",
        "captured_everything": False,
        "error": "SESSION_STORE_URL is not set",
        "store_url": None,
        "origin": None,
    }
)


@pytest.mark.unit
class TestSuccessIsHardToReachByAccident:
    """CAPTURED is the only state that does not set needs_backfill.

    It is the verdict that decides a session is safe to stop worrying about, so
    every check here exists to make reaching it by accident harder.
    """

    def test_success_against_the_wrong_store_is_not_captured(self) -> None:
        # The counters cannot tell a right store from a wrong one, and neither
        # can the exit code. Only the caller knows where it meant them to go.
        out = parse_capture_result(
            _CLEAN,
            0,
            store_enabled=True,
            expected_store_url="http://the-real-store:8799",
        )
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill
        assert "not the configured" in (out.reason or "")

    def test_success_tagged_for_another_deployment_is_not_captured(self) -> None:
        out = parse_capture_result(
            _CLEAN, 0, store_enabled=True, expected_deployment="syntropic137__prod"
        )
        assert out.state is CaptureState.UNKNOWN
        assert "not this deployment" in (out.reason or "")

    def test_matching_expectations_still_reads_captured(self) -> None:
        # The checks must not make CAPTURED unreachable.
        out = parse_capture_result(
            _CLEAN,
            0,
            store_enabled=True,
            expected_store_url="http://host.docker.internal:8799",
            expected_deployment="syntropic137__dev",
        )
        assert out.state is CaptureState.CAPTURED
        assert not out.needs_backfill

    def test_a_document_that_contradicts_itself_is_not_captured(self) -> None:
        # v0.3.0 cannot emit this: it derives both the exit code and the
        # boolean FROM these counters. The check costs nothing today and fails
        # closed if the producer gains a bug or this parser drifts from it.
        doc = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "counters": {"discovered": 1, "uploaded": 1, "rejected": 1},
            }
        )
        out = parse_capture_result(doc, 0, store_enabled=True)
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill
        assert "rejected=1" in (out.reason or "")

    def test_a_zero_discovery_sweep_says_so(self) -> None:
        # A sweep that found nothing is not a failure, but "sessions are in the
        # store" is not true of it either. The distinction is recorded rather
        # than flattened, so a caller that expected a session can notice.
        doc = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "counters": {"discovered": 0, "uploaded": 0, "accepted": 0},
            }
        )
        out = parse_capture_result(doc, 0, store_enabled=True)
        assert out.state is CaptureState.CAPTURED
        assert not out.needs_backfill
        assert "discovered=0" in (out.reason or "")


@pytest.mark.unit
class TestConfigurationFailure:
    def test_a_config_error_is_failed_and_carries_no_invented_destination(self) -> None:
        out = parse_capture_result(_CONFIG_ERROR, 1, store_enabled=True)
        assert out.state is CaptureState.FAILED
        assert out.needs_backfill
        assert "SESSION_STORE_URL" in (out.reason or "")
        # null rather than "" - an absent destination must not read as a
        # configured-but-blank one.
        assert out.store_url is None
        assert out.origin_environment is None
