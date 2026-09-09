"""Tests for the shared justfile model.

Every case here is a shape one of the four regexes this module replaced could
not see (#1125). They are written as "the model finds X" rather than "the regex
was wrong" because the point is the model's contract, but each one failed
against what came before - a test that only exercises `name:` with no
parameters and no body passes against the broken version too, which is how the
gap survived this long.
"""

from __future__ import annotations

import pytest
from scripts.justfile_model import Justfile, UnknownRecipeError

pytestmark = pytest.mark.unit


def test_a_recipe_with_parameters_is_a_recipe() -> None:
    """`^name:` never matched one, so twenty-nine recipes did not exist."""
    justfile = Justfile.parse(
        "release-local version:\n    @echo {{version}}\n\n"
        'validate-pre-merge quick="":\n    @echo {{quick}}\n\n'
        "selfhost-logs *service:\n    @echo {{service}}\n\n"
        "release-retag image from to:\n    @echo hi\n"
    )

    assert justfile.names == {
        "release-local",
        "validate-pre-merge",
        "selfhost-logs",
        "release-retag",
    }


def test_a_parameterised_recipe_still_has_dependencies() -> None:
    """The blind spot above hid everything downstream of it, too."""
    justfile = Justfile.parse(
        'release-local-full version from="v1": check-version\n    @echo hi\n\n'
        "check-version:\n    @echo v\n"
    )

    assert justfile.closure("release-local-full") == {"release-local-full", "check-version"}


def test_a_recipe_invoked_from_a_body_is_reached() -> None:
    """`codegen-check` runs `just codegen`; a header-only walk called it unrun."""
    justfile = Justfile.parse(
        "codegen-check:\n    #!/usr/bin/env bash\n    just codegen > /dev/null\n\n"
        "codegen: docs-cli-gen\n    @echo gen\n\n"
        "docs-cli-gen:\n    @echo docs\n"
    )

    assert justfile.closure("codegen-check") == {"codegen-check", "codegen", "docs-cli-gen"}


@pytest.mark.parametrize(
    "line",
    [
        'echo "   • View logs:     just dev-logs"',
        "echo 'run just dev-logs when ready'",
        "echo \"❌ drift. Run 'just dev-logs' and commit\"",
    ],
)
def test_a_recipe_named_inside_quotes_is_not_invoked(line: str) -> None:
    """The direction that would LOSE findings: a mention read as a call grows
    the closure and hides a real orphan. Quoted text is a message, not a run."""
    justfile = Justfile.parse(f"help:\n    {line}\n\ndev-logs:\n    @echo logs\n")

    assert justfile.recipes["help"].runs == frozenset()


def test_a_recipe_named_in_a_comment_is_not_invoked() -> None:
    """The justfile's prose says `just preflight` in several places."""
    justfile = Justfile.parse(
        "help:\n    # run just dev-logs afterwards\n    @echo hi\n\ndev-logs:\n    @echo l\n"
    )

    assert justfile.recipes["help"].runs == frozenset()


def test_the_comment_block_above_a_recipe_belongs_to_neither() -> None:
    """Comments sit at column 0, so a naive "everything until the next header"
    would attribute the NEXT recipe's documentation to THIS one's body."""
    justfile = Justfile.parse(
        "first:\n    @echo one\n\n# Run `just dev-logs` to watch it.\nsecond:\n    @echo two\n"
    )

    assert justfile.recipes["first"].runs == frozenset()
    assert justfile.recipes["second"].runs == frozenset()


def test_a_quiet_recipe_is_a_recipe() -> None:
    """`@name:` suppresses echoing. It would have been a free naming dodge."""
    assert Justfile.parse("@quiet-gate:\n    echo hi\n").names == {"quiet-gate"}


def test_assignments_are_not_recipes() -> None:
    """`:=` binds a variable. Reading one as a recipe would invent gates."""
    justfile = Justfile.parse(
        "set dotenv-load := true\n"
        'compose := "docker compose -f docker/docker-compose.yaml"\n'
        'export TOKEN := "x"\n'
        "real:\n    @echo hi\n"
    )

    assert justfile.names == {"real"}


def test_a_flag_is_not_a_recipe_name() -> None:
    """`@just --list` must not register a recipe called `--list`."""
    assert Justfile.parse("help:\n    @just --list\n").recipes["help"].runs == frozenset()


def test_only_defined_recipes_count_as_edges() -> None:
    """`just` calls a shell tool of the same name in some bodies; a dependency
    on something the justfile does not define is not a dependency."""
    assert Justfile.parse("solo:\n    just not-a-recipe\n").recipes["solo"].runs == frozenset()


def test_a_dependency_cycle_terminates() -> None:
    justfile = Justfile.parse("a: b\n    @echo a\n\nb: a\n    @echo b\n")

    assert justfile.closure("a") == {"a", "b"}


def test_asking_for_a_root_that_does_not_exist_is_an_error() -> None:
    """Renaming `preflight` must break its guard, not empty it silently."""
    with pytest.raises(UnknownRecipeError):
        Justfile.parse("lint:\n    @echo hi\n").closure("preflight")


def test_commands_run_by_reports_what_those_recipes_actually_execute() -> None:
    """Used to ask "does any local target run this script?"."""
    justfile = Justfile.parse(
        "gate:\n    # not a command\n    uv run python scripts/check_thing.py\n\n"
        "other:\n    uv run python scripts/unrelated.py\n"
    )
    commands = justfile.commands_run_by(frozenset({"gate"}))

    assert "scripts/check_thing.py" in commands
    assert "scripts/unrelated.py" not in commands
    assert "not a command" not in commands
