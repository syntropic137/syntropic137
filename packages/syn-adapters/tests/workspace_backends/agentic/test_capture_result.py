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
    CaptureExpectations,
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


#: What the fixtures above were actually produced against. Spelled once so a
#: test that means to assert a MISMATCH has to say so explicitly.
_CLEAN_EXPECT = CaptureExpectations(
    store_url="http://host.docker.internal:8799", deployment="syntropic137__dev"
)
_REJECTED_EXPECT = CaptureExpectations(store_url="http://127.0.0.1:8793", deployment=None)
_UNREACHABLE_EXPECT = CaptureExpectations(
    store_url="http://127.0.0.1:1", deployment="syntropic137__dev"
)


def _parse(
    stdout: str,
    exit_code: int,
    *,
    expectations: CaptureExpectations | None = _CLEAN_EXPECT,
):
    """Call the parser, defaulting to the expectations `_CLEAN` was made under.

    The production signature has no default and no unchecked mode: expectations
    are None exactly when no store is configured. This helper carries a default
    only so tests that are about something else stay readable; anything
    asserting a destination mismatch passes its own.
    """
    return parse_capture_result(stdout, exit_code, expectations=expectations)


@pytest.mark.unit
class TestTheThreeRealOutcomes:
    def test_a_clean_sweep_is_captured(self) -> None:
        out = _parse(_CLEAN, 0)
        assert out.state is CaptureState.CAPTURED
        assert not out.needs_backfill
        assert out.origin_deployment == "syntropic137__dev"
        assert out.store_url == "http://host.docker.internal:8799"

    def test_a_rejected_sweep_is_incomplete_and_names_the_loss(self) -> None:
        out = _parse(_REJECTED, 3, expectations=_REJECTED_EXPECT)
        assert out.state is CaptureState.INCOMPLETE
        assert out.needs_backfill
        assert "rejected=1" in (out.reason or "")

    def test_an_unreachable_store_is_failed_and_carries_the_error(self) -> None:
        out = _parse(_UNREACHABLE, 1, expectations=_UNREACHABLE_EXPECT)
        assert out.state is CaptureState.FAILED
        assert out.needs_backfill
        assert "not reachable" in (out.reason or "")


@pytest.mark.unit
class TestTheVerdictIsNeverGuessed:
    def test_a_disabled_store_is_not_a_failure(self) -> None:
        out = _parse("", 0, expectations=None)
        assert out.state is CaptureState.DISABLED
        assert not out.needs_backfill

    def test_an_unknown_schema_version_is_refused(self) -> None:
        # The exporter bumps this on any incompatible change precisely so a
        # consumer can refuse rather than misread. Guessing would mean reading
        # a field that may have changed meaning.
        doc = json.dumps(
            {"schema_version": SUPPORTED_SCHEMA_VERSION + 1, "captured_everything": True}
        )
        out = _parse(doc, 0)
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill

    def test_no_document_is_not_success(self) -> None:
        # An exporter older than --json exits 0 and prints a prose line. That
        # is a misconfiguration, not a capture, and must never read as one.
        out = _parse("run: discovered=1 uploaded=1 accepted=1 failed=0", 0)
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill
        assert "predate" in (out.reason or "")

    def test_exit_code_contradicting_the_document_is_unknown(self) -> None:
        # Both come from the same process. If they disagree, something is wrong
        # with the exporter or the invocation, and preferring whichever says
        # what we want is exactly how a false verdict gets recorded.
        out = _parse(_CLEAN, 3)
        assert out.state is CaptureState.UNKNOWN
        assert "contradicts" in (out.reason or "")

    def test_a_usage_error_is_our_bug_not_the_stores(self) -> None:
        out = _parse("", 2)
        assert out.state is CaptureState.UNKNOWN
        assert "arguments" in (out.reason or "")

    def test_a_missing_captured_everything_is_unknown(self) -> None:
        doc = json.dumps({"schema_version": 1, "counters": {"failed": 0}})
        out = _parse(doc, 0)
        assert out.state is CaptureState.UNKNOWN


@pytest.mark.unit
class TestParsingIsDefensive:
    def test_leading_noise_does_not_break_the_verdict(self) -> None:
        # A wrapper prepending output is a realistic accident. Being strict
        # about it would turn a cosmetic problem into an unreadable verdict.
        out = _parse(f"some wrapper noise\n{_CLEAN}", 0)
        assert out.state is CaptureState.CAPTURED

    def test_non_integer_counters_are_dropped_not_coerced(self) -> None:
        doc = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "store_url": "http://host.docker.internal:8799",
                "origin": {"environment": "container", "deployment": "syntropic137__dev"},
                "counters": {"uploaded": 1, "accepted": "one", "failed": True},
            }
        )
        out = _parse(doc, 0)
        assert out.counters == {"uploaded": 1}, out.counters

    def test_garbage_is_unknown_rather_than_an_exception(self) -> None:
        out = _parse("{not json at all", 0)
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
        out = _parse(
            _CLEAN,
            0,
            expectations=CaptureExpectations(
                store_url="http://the-real-store:8799", deployment="syntropic137__dev"
            ),
        )
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill
        assert "not the configured" in (out.reason or "")

    def test_success_tagged_for_another_deployment_is_not_captured(self) -> None:
        out = _parse(
            _CLEAN,
            0,
            expectations=CaptureExpectations(
                store_url="http://host.docker.internal:8799",
                deployment="syntropic137__prod",
            ),
        )
        assert out.state is CaptureState.UNKNOWN
        assert "not the expected" in (out.reason or "")

    def test_matching_expectations_still_reads_captured(self) -> None:
        # The checks must not make CAPTURED unreachable.
        out = _parse(_CLEAN, 0, expectations=_CLEAN_EXPECT)
        assert out.state is CaptureState.CAPTURED
        assert not out.needs_backfill

    @pytest.mark.parametrize("counter", ["rejected", "failed", "skipped_oversize", "unconfirmed"])
    def test_any_loss_counter_contradicting_success_is_not_captured(self, counter: str) -> None:
        # Parameterised across all four, because testing one proves only that
        # the branch exists, not that the set it checks is the right set.
        doc = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "store_url": "http://host.docker.internal:8799",
                "origin": {"environment": "container", "deployment": "syntropic137__dev"},
                "counters": {"discovered": 1, "uploaded": 1, counter: 1},
            }
        )
        out = _parse(doc, 0)
        assert out.state is CaptureState.UNKNOWN, counter
        assert out.needs_backfill, counter
        assert f"{counter}=1" in (out.reason or ""), out.reason

    def test_a_document_with_no_discovered_count_is_not_captured(self) -> None:
        # "Everything reached the store" is a claim about a set. Without a
        # discovered count the document cannot say what that set was, so the
        # claim is unverifiable rather than true.
        doc = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "store_url": "http://host.docker.internal:8799",
                "origin": {"environment": "container", "deployment": "syntropic137__dev"},
                "counters": {"uploaded": 1, "accepted": 1},
            }
        )
        out = _parse(doc, 0)
        assert out.state is CaptureState.UNKNOWN
        assert out.needs_backfill
        assert "discovered" in (out.reason or "")

    def test_a_document_that_contradicts_itself_is_not_captured(self) -> None:
        # v0.3.0 cannot emit this: it derives both the exit code and the
        # boolean FROM these counters. The check costs nothing today and fails
        # closed if the producer gains a bug or this parser drifts from it.
        doc = json.dumps(
            {
                "schema_version": 1,
                "captured_everything": True,
                "store_url": "http://host.docker.internal:8799",
                "origin": {"environment": "container", "deployment": "syntropic137__dev"},
                "counters": {"discovered": 1, "uploaded": 1, "rejected": 1},
            }
        )
        out = _parse(doc, 0)
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
                "store_url": "http://host.docker.internal:8799",
                "origin": {"environment": "container", "deployment": "syntropic137__dev"},
                "counters": {"discovered": 0, "uploaded": 0, "accepted": 0},
            }
        )
        out = _parse(doc, 0)
        assert out.state is CaptureState.CAPTURED
        assert not out.needs_backfill
        assert "discovered=0" in (out.reason or "")


@pytest.mark.unit
class TestConfigurationFailure:
    def test_a_config_error_is_failed_and_carries_no_invented_destination(self) -> None:
        out = _parse(_CONFIG_ERROR, 1, expectations=_UNREACHABLE_EXPECT)
        assert out.state is CaptureState.FAILED
        assert out.needs_backfill
        assert "SESSION_STORE_URL" in (out.reason or "")
        # null rather than "" - an absent destination must not read as a
        # configured-but-blank one.
        assert out.store_url is None
        assert out.origin_environment is None
