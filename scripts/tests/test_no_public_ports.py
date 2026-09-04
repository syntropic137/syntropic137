"""Unit tests for the no-public-ports gate.

Every fixture under `fixtures/no_public_ports/` was run against the version of
this gate that PRECEDED it before being written down, and the file names record
what that version did with them. None of them is an assertion that the current
code does what it currently does.

Six were run against the original awk gate, which counted colons:

    waved_through_by_colon_count.{yaml,sh}  old gate: ok, exit 0
    never_scanned_at_all.yaml               old gate: ok, exit 0
    defaults_only_guarantee.yaml            old gate: ok, exit 0 (also with
                                            BIND=0.0.0.0 exported)
    long_syntax_verdicts_inverted.yaml      old gate: flagged the SAFE entry at
                                            line 19 and missed the unsafe one
                                            at line 9
    safe.yaml                               old gate: flagged line 26, a
                                            correctly written long-form publish
    no_host_port_at_all.yaml                old gate: flagged all three, but
                                            because they have fewer than two
                                            colons, not because anything asked
                                            what they bind

Three more were run against the FIRST YAML-aware version (d2ed8a64), which
fixed the colon counting and was then found to have three holes of its own.
All three exited 0 on the fixture that now covers them:

    inherited_through_a_merge_key.yaml      d2ed8a64: 1 publish found, exit 0 -
                                            it returned the literal `<<` entry,
                                            so two publicly-binding services
                                            inheriting `ports` were never walked
    interpolation_outside_the_host_ip_      d2ed8a64: 2 publishes found, exit 0,
      field.yaml                            and binding_variables() returned []
                                            for both, so an undeclared variable
                                            choosing the interface was reported
                                            nowhere
    compact_publish_flag.sh                 d2ed8a64: 0 publishes found, exit 0 -
                                            the flag pattern required a
                                            separator, so `-p5432:5432` matched
                                            nothing, while `--publish=5432:5432`
                                            was rejected correctly

Each one is a case the shipped gate got wrong, in one of the two directions.

They drive `evaluate()` - the verdict a human actually reads - rather than the
classification helpers, and they assert the LINE NUMBERS in that rendered
output. A gate that finds the right entry and then reports it at the wrong
place, or drops it between the parser and the message, is a gate nobody can
act on, and asserting on the helper would not notice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts.no_public_ports import (
    DECLARED_OPERATOR_BINDS,
    evaluate,
    publishes_in_compose,
    publishes_in_shell,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "no_public_ports"

_REPORTED = re.compile(r"^no_public_ports: [^:]+:(\d+) -- (.*)$")


def verdict(name: str) -> tuple[int, dict[int, str]]:
    """Run the gate over one fixture and read the flagged lines back out of its output."""
    path = FIXTURES / name
    text = path.read_text()
    publishes = (
        publishes_in_compose(name, text)
        if path.suffix == ".yaml"
        else publishes_in_shell(name, text)
    )
    code, lines = evaluate(publishes)
    flagged = {
        int(match.group(1)): match.group(2)
        for line in lines
        if (match := _REPORTED.match(line)) is not None
    }
    return code, flagged


class TestSpellingsTheColonCounterWavedThrough:
    """Six short-syntax publishes that bind every interface and passed, exit 0."""

    def test_every_one_of_them_is_now_rejected(self) -> None:
        code, flagged = verdict("waved_through_by_colon_count.yaml")
        assert code == 1
        assert sorted(flagged) == [9, 13, 17, 21, 25, 29]

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            (9, "not loopback"),  # "0.0.0.0:15432:5432"
            (13, "not loopback"),  # unquoted 0.0.0.0:15432:5432
            (17, "not loopback"),  # "[::]:15432:5432"
            (21, "not loopback"),  # "0.0.0.0:15432-15434:5432-5434"
            (25, "empty host interface"),  # "::5432"
            (29, "empty host interface"),  # "${BIND}:15432:5432", BIND unset
        ],
    )
    def test_each_is_rejected_for_what_it_binds(self, line: int, expected: str) -> None:
        _, flagged = verdict("waved_through_by_colon_count.yaml")
        assert expected in flagged[line]

    def test_a_wildcard_host_is_rejected_as_an_address_not_as_a_magic_string(self) -> None:
        """`0.0.0.0` and `::` are rejected because they are not loopback, so the
        next spelling nobody thought of - a LAN address - is rejected too."""
        _, flagged = verdict("waved_through_by_colon_count.yaml")
        assert "'0.0.0.0'" in flagged[9]
        assert "'::'" in flagged[17]


class TestSpellingsTheOldGateNeverScannedAtAll:
    """Flow style, a trailing comment, a quoted key and an alias: four ways to
    write `ports:` that the `^\\s*ports:\\s*$` state machine could not enter."""

    def test_all_four_are_now_rejected(self) -> None:
        code, flagged = verdict("never_scanned_at_all.yaml")
        assert code == 1
        assert sorted(flagged) == [5, 10, 14, 18]

    def test_the_alias_is_reported_where_the_anchor_is_written(self) -> None:
        """`ports: *public_ports` resolves to the anchored sequence, so the
        entry is reported at line 5, where the value a human has to change is
        actually written, and not at the reference on line 21."""
        _, flagged = verdict("never_scanned_at_all.yaml")
        assert 21 not in flagged
        assert "no host interface" in flagged[5]


class TestLongSyntaxVerdictsWereInverted:
    def test_the_unsafe_flow_mapping_that_used_to_pass_is_rejected(self) -> None:
        """Line 9 has four colons inside a flow mapping and no `host_ip` at all."""
        code, flagged = verdict("long_syntax_verdicts_inverted.yaml")
        assert code == 1
        assert "long syntax with no host_ip" in flagged[9]

    def test_the_unsafe_block_mapping_stays_rejected(self) -> None:
        _, flagged = verdict("long_syntax_verdicts_inverted.yaml")
        assert "long syntax with no host_ip" in flagged[13]

    @pytest.mark.parametrize("line", [19, 25])
    def test_long_syntax_that_names_a_loopback_host_ip_is_accepted(self, line: int) -> None:
        """Line 19 is the false positive the old gate raised on every correctly
        written long-form publish, block or flow."""
        _, flagged = verdict("long_syntax_verdicts_inverted.yaml")
        assert line not in flagged


class TestPublishesWithNoHostPortAtAll:
    """Already rejected before, but by colon arithmetic. Kept so the semantic
    rule that replaced it is pinned to the same answer."""

    def test_all_three_are_rejected(self) -> None:
        code, flagged = verdict("no_host_port_at_all.yaml")
        assert code == 1
        assert sorted(flagged) == [9, 13, 17]

    def test_an_integer_entry_is_read_as_a_publish_and_not_skipped(self) -> None:
        """`- 5432` parses as an int, not a string; a checker that assumed
        strings would silently ignore the entry that gets a RANDOM public port."""
        _, flagged = verdict("no_host_port_at_all.yaml")
        assert "no host port at all" in flagged[9]

    def test_a_protocol_suffix_does_not_disguise_a_missing_host_port(self) -> None:
        _, flagged = verdict("no_host_port_at_all.yaml")
        assert "no host port at all" in flagged[13]

    def test_a_host_port_without_an_interface_is_named_as_such(self) -> None:
        _, flagged = verdict("no_host_port_at_all.yaml")
        assert "no host interface" in flagged[17]


class TestSafeFormsAreAccepted:
    def test_the_whole_fixture_passes(self) -> None:
        """Including line 26, the long-form publish the old gate rejected. A
        gate that fails what it is asking people to write teaches them to
        ignore it."""
        code, flagged = verdict("safe.yaml")
        assert flagged == {}
        assert code == 0

    def test_the_declared_operator_variable_is_not_confused_with_the_port_variable(self) -> None:
        """`${SYN_ENV_BIND:-127.0.0.1}:${SYN_ENV_PORT_DB}:5432` interpolates two
        variables and only the first chooses an interface. Blaming both would
        fail this line for the undeclared port variable."""
        code, _ = verdict("safe.yaml")
        assert code == 0
        assert "SYN_ENV_PORT_DB" not in DECLARED_OPERATOR_BINDS


class TestTheGuaranteeIsAboutDefaults:
    """The second defect: `SYN_GATEWAY_BIND=0.0.0.0` made real mappings resolve
    to 0.0.0.0 while the gate printed ok, because it stripped `${...}` and
    counted what was left."""

    def test_an_undeclared_host_ip_variable_is_rejected_even_when_its_default_is_loopback(
        self,
    ) -> None:
        code, flagged = verdict("defaults_only_guarantee.yaml")
        assert code == 1
        assert sorted(flagged) == [11, 15]
        assert "${BIND}" in flagged[11]
        assert "${BIND6}" in flagged[15]

    def test_a_declared_operator_override_is_accepted(self) -> None:
        _, flagged = verdict("defaults_only_guarantee.yaml")
        assert 19 not in flagged

    def test_a_clean_run_states_that_it_only_checked_defaults(self) -> None:
        """The gate is allowed to make a narrower promise than "not public",
        but it has to say so where someone reading a green run will see it."""
        path = FIXTURES / "safe.yaml"
        code, lines = evaluate(publishes_in_compose("safe.yaml", path.read_text()))
        assert code == 0
        assert any("this checks DEFAULTS" in line for line in lines)

    def test_a_clean_run_names_the_variables_that_can_undo_it(self) -> None:
        path = FIXTURES / "safe.yaml"
        _, lines = evaluate(publishes_in_compose("safe.yaml", path.read_text()))
        assert any("SYN_ENV_BIND=0.0.0.0" in line for line in lines)

    def test_a_run_with_nothing_overridable_makes_no_such_claim(self) -> None:
        """The disclaimer has to be earned by an actual variable, or it is
        noise that trains people to skip the second line."""
        _, lines = evaluate(
            publishes_in_compose("x.yaml", 'services: {a: {ports: ["127.0.0.1:1:1"]}}')
        )
        assert not any("DEFAULTS" in line for line in lines)


class TestShellPublishes:
    """`docker run -p` has the same defect, and the same fixture treatment."""

    def test_every_unsafe_spelling_is_rejected(self) -> None:
        code, flagged = verdict("waved_through_by_colon_count.sh")
        assert code == 1
        assert sorted(flagged) == [6, 7, 8, 9, 10]

    def test_a_quoted_argument_is_no_longer_a_way_past_the_gate(self) -> None:
        """This is the shape that was live in this repo's justfile: the old
        pattern required the argument to start with a digit or `$`, so the
        opening quote skipped the line."""
        _, flagged = verdict("waved_through_by_colon_count.sh")
        assert "no host interface" in flagged[9]

    def test_a_dotted_quad_is_not_accepted_merely_for_being_dotted(self) -> None:
        _, flagged = verdict("waved_through_by_colon_count.sh")
        assert "'0.0.0.0'" in flagged[6]
        assert "'0.0.0.0'" in flagged[7]

    def test_safe_publishes_and_unrelated_dash_p_flags_are_left_alone(self) -> None:
        """`mkdir -p`, `cargo build -p` and an echoed `-p` all share the flag.
        A gate that flags them gets switched off."""
        code, flagged = verdict("safe.sh")
        assert flagged == {}
        assert code == 0


class TestPortsInheritedThroughAMergeKey:
    """A `<<` merge key is the third way a service acquires `ports`, and the
    one the first YAML-aware version did not walk: it read the literal `<<`
    entry and never looked at what it inherits, so the document reported zero
    publishes and exited 0 with two publicly-binding services in it."""

    def test_a_service_that_inherits_ports_is_judged_on_them(self) -> None:
        code, flagged = verdict("inherited_through_a_merge_key.yaml")
        assert code == 1
        assert "no host interface" in flagged[14]

    def test_the_inherited_entry_is_reported_where_the_anchor_is_written(self) -> None:
        """Line 14 is inside `x-inherited-public`, the mapping a human has to
        change; line 28 is only the `<<:` that pulls it in. Same rule as the
        alias case, and the reason merge is resolved on the node graph rather
        than by copying text."""
        _, flagged = verdict("inherited_through_a_merge_key.yaml")
        assert 28 not in flagged

    def test_ports_written_on_the_service_win_over_the_inherited_ones(self) -> None:
        """`own_ports_win_over_the_inherited_ones` merges a 0.0.0.0 anchor AND
        writes its own loopback `ports`. YAML gives the local key precedence, so
        line 17 is a mapping docker never applies - flagging it would fail a
        service that is correctly configured, which is how a gate loses its
        credibility. Line 17 is reachable ONLY through this service, so it is
        flagged if and only if the precedence is inverted."""
        _, flagged = verdict("inherited_through_a_merge_key.yaml")
        assert 17 not in flagged

    def test_the_earlier_source_of_a_merge_list_wins(self) -> None:
        """`<<: [*loopback_base, *later_public]` resolves to the loopback ports
        on line 20. Taking the last source instead binds 0.0.0.0 and would flag
        line 23, which nothing else in this fixture can reach."""
        _, flagged = verdict("inherited_through_a_merge_key.yaml")
        assert 23 not in flagged

    def test_no_other_entry_in_the_document_is_flagged(self) -> None:
        """Stated as an exact set so a merge rule that pulls in a mapping which
        does not apply shows up as an extra line rather than passing unnoticed."""
        _, flagged = verdict("inherited_through_a_merge_key.yaml")
        assert sorted(flagged) == [14]


class TestVariablesThatChooseTheInterfaceFromOutsideTheHostIpField:
    """The defaults-only promise is that any variable able to flip a bind
    public is NAMED. The first YAML-aware version only credited variables whose
    marker landed inside the parsed host-IP field, so a variable supplying the
    whole mapping - or a leading run of it - chose the interface with nothing
    reported at all, and the run was clean."""

    def test_both_are_rejected_as_undeclared_operator_overrides(self) -> None:
        code, flagged = verdict("interpolation_outside_the_host_ip_field.yaml")
        assert code == 1
        assert sorted(flagged) == [16, 20]

    def test_a_variable_supplying_the_whole_mapping_is_named(self) -> None:
        """`${PUBLISH:-127.0.0.1:15432:5432}` is loopback unset and picks a
        random port on every interface when an operator exports it."""
        _, flagged = verdict("interpolation_outside_the_host_ip_field.yaml")
        assert "${PUBLISH}" in flagged[16]
        assert "DECLARED_OPERATOR_BINDS" in flagged[16]

    def test_a_variable_supplying_part_of_the_mapping_is_named(self) -> None:
        """`${DB_BIND:-127.0.0.1:15432}:5432` spans the boundary between the
        host interface and the host port, so it belongs to neither field and
        was credited to neither."""
        _, flagged = verdict("interpolation_outside_the_host_ip_field.yaml")
        assert "${DB_BIND}" in flagged[20]

    def test_a_port_variable_is_still_not_blamed_for_the_interface(self) -> None:
        """The reason the narrow rule existed. `safe.yaml` interpolates
        `${SYN_ENV_PORT_DB}` into the host PORT of an otherwise safe mapping;
        widening the question from "where is it written" to "can it move the
        bind" must not start failing that line, or the fix trades a silent miss
        for a false positive on the spelling the gate asks people to use."""
        code, lines = evaluate(
            publishes_in_compose("safe.yaml", (FIXTURES / "safe.yaml").read_text())
        )
        assert code == 0
        assert any("SYN_ENV_BIND=0.0.0.0" in line for line in lines)
        assert not any("SYN_ENV_PORT_DB" in line for line in lines)


class TestTheCompactPublishFlag:
    """`docker run -p5432:5432` - no separator. The first YAML-aware version
    required `[=\\s]+` after the flag, so it found nothing on any of these
    lines and exited 0, while `--publish=5432:5432` was rejected correctly."""

    def test_every_compact_spelling_is_found_and_judged(self) -> None:
        code, flagged = verdict("compact_publish_flag.sh")
        assert code == 1
        assert sorted(flagged) == [9, 10, 11]

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            (9, "no host interface"),  # -p5432:5432
            (10, "'0.0.0.0'"),  # -p"0.0.0.0:5432:5432"
            (11, "'::'"),  # -p'[::]:5432:5432'
        ],
    )
    def test_each_is_rejected_for_what_it_binds(self, line: int, expected: str) -> None:
        """Compact quoting included: the shell strips the quote whether or not a
        space precedes it, so `-p"..."` publishes exactly what `-p "..."` does."""
        _, flagged = verdict("compact_publish_flag.sh")
        assert expected in flagged[line]

    def test_non_publish_uses_of_the_flag_survive_the_looser_separator(self) -> None:
        """Making the separator optional means `-p` now matches with anything
        after it, so `mkdir -p workspaces` and `cargo build -p aps-cli` are
        candidates on every run. They are still excluded by what the argument
        LOOKS like, which is the only thing that ever excluded them."""
        code, flagged = verdict("safe.sh")
        assert flagged == {}
        assert code == 0
