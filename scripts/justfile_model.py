"""One parse of the justfile, shared by every check that asks "what runs what?".

WHY THIS EXISTS (issue #1125). Four separate regexes used to answer that
question - two in `check_ci_parity.py`, two in the fitness test beside it - and
every one of them was blind to something:

- ``^name:`` never matches a recipe that takes a parameter, so `release-local`
  and twenty others were invisible, along with anything they depend on.
- A dependency closure built from recipe HEADERS alone misses a recipe invoked
  from a recipe BODY. `codegen-check` runs `just codegen` and `fitness-check`
  runs `just topology-analyze`; both were papered over by hand-written
  exception entries amounting to "actually, something does run this".
- ``check-*`` / ``*-check`` discovers gates by NAME, so a gate called anything
  else was not discovered at all. That is #1125 itself.

They are all one defect: the check passed for a case it never examined. Fixing
them separately would leave four regexes to drift apart again, so there is now
one parse and one answer.

WHAT A RECIPE "RUNS" IS A DECISION THIS MODULE HIDES. Callers ask
``closure(root)`` and get every recipe that root reaches. Whether an edge came
from a header dependency or from a `just` call in a body is an implementation
detail, and making it one is what let two exception entries be deleted rather
than maintained.

WHY TEXT AND NOT ``just --dump``. `just` owns the only parser that is right by
definition, and `test_ci_and_preflight_agree.py` cross-checks this module
against it. But `just` is not installed in the CI job that runs the unit tests,
so a model requiring the binary could not be tested there - and a check that
cannot run is the failure mode this file exists to prevent.

BLIND SPOTS, STATED. Body scanning cannot resolve `just "$TARGET"`, and it
ignores text inside quotes so `echo "run just dev-logs"` is not read as an
invocation. Both make the closure SMALLER, never larger, so both can only
produce a recipe wrongly reported as unrun - never a real orphan hidden. The
asymmetry is deliberate: over-approximating the closure is the direction that
loses findings.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
JUSTFILE: Final = REPO_ROOT / "justfile"

#: A recipe header at column 0: an optional `@`, the name, optional parameters,
#: then `:` - but not `:=`, which is an assignment - and optional dependencies.
#: Anchored at column 0 because `just` requires every body line to be indented.
_HEADER: Final = re.compile(
    r"^@?(?P<name>[A-Za-z_][A-Za-z0-9_-]*)(?P<params>[^:\n#]*):(?!=)(?P<deps>[^\n#]*)$",
    re.MULTILINE,
)

#: Names in a dependency list, including the `(dep arg)` call form.
_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")

#: A quoted span, removed before a body line is read for invocations: the text
#: in `echo "run just dev-logs"` names a recipe without running it.
_QUOTED: Final = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")

#: `just <recipe>` in a body. A flag starts with `-` and so cannot match, which
#: is what keeps `just --list` from being read as a recipe named `--list`.
_INVOCATION: Final = re.compile(r"\bjust\s+([A-Za-z_][A-Za-z0-9_-]*)")


class UnknownRecipeError(LookupError):
    """A closure was asked for from a root the justfile does not define."""


@dataclass(frozen=True)
class Recipe:
    """One recipe: where it is written, what it runs, and what it does."""

    name: str
    line: int
    runs: frozenset[str]
    body: tuple[str, ...]


@dataclass(frozen=True)
class Justfile:
    """Every recipe the justfile defines, and what each one runs."""

    recipes: Mapping[str, Recipe]

    @classmethod
    def parse(cls, text: str) -> Justfile:
        lines = text.split("\n")
        headers = [
            (m.group("name"), text[: m.start()].count("\n") + 1, m.group("deps"))
            for m in _HEADER.finditer(text)
        ]
        names = {name for name, _, _ in headers}

        recipes: dict[str, Recipe] = {}
        for index, (name, line, deps) in enumerate(headers):
            end = headers[index + 1][1] - 1 if index + 1 < len(headers) else len(lines)
            body = tuple(_commands(lines[line:end]))
            recipes[name] = Recipe(
                name=name,
                line=line,
                runs=frozenset(_NAME.findall(deps) + _invoked(body)) & names,
                body=body,
            )
        return cls(recipes=recipes)

    @classmethod
    def load(cls, path: Path = JUSTFILE) -> Justfile:
        return cls.parse(path.read_text())

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.recipes)

    def closure(self, root: str) -> frozenset[str]:
        """`root` and every recipe reachable from it, transitively."""
        if root not in self.recipes:
            raise UnknownRecipeError(f"the justfile defines no `{root}` recipe")
        seen: set[str] = set()
        stack = [root]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.recipes[current].runs)
        return frozenset(seen)

    def commands_run_by(self, targets: frozenset[str]) -> str:
        """Every command line those recipes run, for asking what they invoke."""
        return "\n".join(
            line for name in sorted(targets) if name in self.recipes for line in self.recipes[name].body
        )


def _commands(body_lines: list[str]) -> list[str]:
    """The lines of a recipe body that are commands.

    A body line is indented - that is `just`'s own rule, and it is what keeps
    the comment block introducing the NEXT recipe out of this one's body. A
    comment is not a command either: the justfile's prose says `just preflight`
    in several places and none of them run it.
    """
    return [
        line
        for line in body_lines
        if line.startswith((" ", "\t")) and not line.strip().startswith("#")
    ]


def _invoked(body: tuple[str, ...]) -> list[str]:
    """Every recipe a body invokes with `just`, ignoring quoted text."""
    return [name for line in body for name in _INVOCATION.findall(_QUOTED.sub(" ", line))]
