"""The platform session id a delegated harness session imports as (#895).

Idempotency rests entirely on this. The import processor can run twice - it
retries under a bound, and it re-runs after a crash - so "have I already
imported this delegate?" has to be answerable without asking anything. A
deterministic id makes the answer structural: the second import addresses the
same aggregate as the first, so it cannot create a second session carrying the
same tokens.

The alternative, minting a uuid4 and recording the mapping somewhere, needs the
mapping to be written in the same transaction as the session or the crash
window reopens. Deriving the id removes the mapping and the window together.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions.import_identity import (
    platform_session_id_for,
)


@pytest.mark.unit
class TestTheSameDelegateAlwaysImportsToTheSameSession:
    def test_it_is_stable_across_calls(self) -> None:
        first = platform_session_id_for("01a0472d-0815-79b0-bda7-ea7c9cb51686")
        second = platform_session_id_for("01a0472d-0815-79b0-bda7-ea7c9cb51686")

        assert first == second

    def test_it_does_not_depend_on_process_state(self) -> None:
        """No clock, no randomness, no counter.

        A restarted processor must derive the same id, or a crash mid-import
        produces a SECOND session carrying the same delegate's tokens - which
        is the double count this whole design exists to prevent, arriving by a
        different road.
        """
        import subprocess
        import sys

        script = (
            "from syn_domain.contexts.agent_sessions.import_identity import "
            "platform_session_id_for; "
            "print(platform_session_id_for('01a0472d-0815-79b0-bda7-ea7c9cb51686'))"
        )
        out = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        )

        assert out.stdout.strip() == platform_session_id_for("01a0472d-0815-79b0-bda7-ea7c9cb51686")


@pytest.mark.unit
class TestDifferentDelegatesDoNotCollide:
    def test_two_harness_sessions_get_two_platform_ids(self) -> None:
        a = platform_session_id_for("01a0472d-0815-79b0-bda7-ea7c9cb51686")
        b = platform_session_id_for("c5e2715f-0a7a-4dde-a8bd-07369601cc94")

        assert a != b

    def test_ids_differing_by_one_character_do_not_collide(self) -> None:
        a = platform_session_id_for("session-a")
        b = platform_session_id_for("session-b")

        assert a != b


@pytest.mark.unit
class TestItIsNotTheHarnessIdItself:
    def test_the_platform_id_differs_from_the_harness_id(self) -> None:
        """The two namespaces must stay separate.

        Reusing the harness id as the platform id would collide the moment two
        harnesses mint the same id, and it would also make a harness id look
        like something the platform issued. They are different namespaces and
        the derivation keeps them so.
        """
        harness = "01a0472d-0815-79b0-bda7-ea7c9cb51686"

        assert platform_session_id_for(harness) != harness

    def test_it_is_a_uuid_string(self) -> None:
        """Platform session ids are uuids elsewhere; an imported one must not
        be visibly different in shape, or it becomes a second class of id that
        every consumer has to know about.
        """
        from uuid import UUID

        value = platform_session_id_for("01a0472d-0815-79b0-bda7-ea7c9cb51686")

        assert str(UUID(value)) == value


@pytest.mark.unit
class TestItRefusesInputItCannotIdentify:
    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_a_blank_harness_id_is_refused(self, blank: str) -> None:
        """Every blank string would derive the SAME id, so two unrelated
        delegates would import into one session and their tokens would merge.
        Refusing is the only safe answer.
        """
        with pytest.raises(ValueError, match="harness session id"):
            platform_session_id_for(blank)
