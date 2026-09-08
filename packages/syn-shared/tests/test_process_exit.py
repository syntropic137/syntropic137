"""The decisions `syn_shared.process_exit` makes on everyone's behalf (#1158).

Every caller hands it an integer and gets back a sentence that will be
persisted and read months later. The tests worth having are the ones where the
integer is ambiguous, because that is where a plausible implementation says
something false.
"""

from __future__ import annotations

import pytest

from syn_shared.process_exit import describe_exit_status, describe_process_failure

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("exit_code", "expected_signal"),
    [
        (137, "SIGKILL"),  # 128 + 9, the form `docker exec` and any shell produce
        (139, "SIGSEGV"),  # 128 + 11, the #1046 crash
        (143, "SIGTERM"),  # 128 + 15, an orderly shutdown killing the phase
        (-9, "SIGKILL"),  # -signum, the form Python's subprocess produces
        (-11, "SIGSEGV"),  # the literal `exit -11` of #1046
    ],
)
def test_both_conventions_for_a_signal_death_name_the_signal(
    exit_code: int, expected_signal: str
) -> None:
    """A caller must not have to know which convention its provider uses.

    `docker exec` reports 128 + signum and Python's `subprocess` reports
    -signum; both are the same death and both used to reach a persisted
    message as a bare number.
    """
    described = describe_exit_status(exit_code)
    assert expected_signal in described
    assert str(exit_code) in described


@pytest.mark.parametrize("exit_code", [1, 2, 125, 128, 255])
def test_a_status_a_program_chose_is_not_dressed_up_as_a_signal(exit_code: int) -> None:
    """Above 128 is not enough: 255 and 128 name no signal and are exits.

    Claiming a signal here would be the same fabrication as hiding one, just
    pointing the other way - and 255 in particular is what asyncio substitutes
    when a child is reaped out from under it (#1065).
    """
    assert describe_exit_status(exit_code) == f"exited {exit_code}"


def test_the_providers_could_not_run_it_sentinel_is_never_read_as_sighup() -> None:
    """-1 is the one negative status that is not a signal number.

    The isolation providers return -1 for three separate ways of never running
    - no container, the exec raised, a timeout - so decoding it as -signum
    would report a SIGHUP death for every unreachable container.
    """
    described = describe_exit_status(-1)
    assert "SIGHUP" not in described
    assert "-1" in described


def test_a_timeout_is_described_as_a_timeout_whatever_status_came_with_it() -> None:
    """Running out of time is neither an exit nor a signal, and outranks both."""
    assert describe_exit_status(-1, timed_out=True) == "timed out, so it did not finish"
    assert describe_exit_status(137, timed_out=True) == "timed out, so it did not finish"


def test_a_killed_process_has_its_output_demoted_below_the_status() -> None:
    """The reproduction from the issue, at the unit that decides it.

    git's clone progress is the whole of stderr when a container dies mid-clone.
    The status has to lead, and the message has to say the output is not a
    reason, or the record reads as a git failure.
    """
    message = describe_process_failure(
        "Setup phase",
        exit_code=137,
        output="Cloning into '/workspace/repos/syntropic137'...",
    )
    assert message.startswith("Setup phase was killed by SIGKILL (exit 137).")
    assert "not an error message" in message
    assert "Cloning into" in message


def test_a_process_that_chose_to_fail_keeps_its_output_as_the_reason() -> None:
    """The other half: a command that ran and refused DID say why, so quote it."""
    message = describe_process_failure(
        "Setup phase",
        exit_code=128,
        output="fatal: could not read Username for 'https://github.com'",
    )
    assert message == (
        "Setup phase exited 128: fatal: could not read Username for 'https://github.com'"
    )


def test_a_silent_failure_says_it_was_silent_rather_than_trailing_off() -> None:
    """#1046 ended in a bare colon and carried nothing at all."""
    message = describe_process_failure("Setup phase", exit_code=-11, output="   \n  ")
    assert message == "Setup phase was killed by SIGSEGV (exit -11) and printed nothing."
