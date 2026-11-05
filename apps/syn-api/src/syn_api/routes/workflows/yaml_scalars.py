"""YAML scalar and flow-list emission for the workflow export.

Split from ``queries`` so the route module stays under the file-size fitness
threshold. Pure functions: what to quote, and how, so an exported package
reinstalls as exactly what was exported."""

from __future__ import annotations

import re

import yaml

# Characters that require quoting in YAML scalar values.
_YAML_SPECIAL_RE = re.compile(r"[:{}\[\],&*?|>!%#@`\"\'\n]")


def _yaml_flow_list(values: list[str]) -> str:
    """A flow list the emitter builds, not string concatenation.

    Quoting each item and joining with ", " is not enough: a value that is a
    perfectly safe standalone scalar can still restructure a FLOW LIST. `a,b`
    reads back as `a,b` on its own and splits into two entries inside
    `[a,b]`, so per-item quoting decided correctly and the surrounding
    context still broke it. The emitter knows both.
    """
    return yaml.safe_dump(values, default_flow_style=True, width=10**9).strip().rstrip("\n")


def _yaml_quote(value: str) -> str:
    """Quote a YAML string unless the bare form reads back as itself.

    Special CHARACTERS are not the whole risk. A value made entirely of
    ordinary characters can still change type: bare `null` parses as None and
    erases the field, `123` becomes an int a string field then rejects, and
    `true`/`no`/`on` become booleans. Those look nothing like injection while
    reading the emitted file, which is why the character test missed them.

    So the check is behavioural rather than syntactic: emit the bare form,
    parse it, and quote unless it survives as the same string. That covers
    every YAML scalar resolution rule without this function having to know
    them.
    """
    if _YAML_SPECIAL_RE.search(value) or not _reads_back_as_itself(value):
        # Delegate to the YAML emitter rather than hand-rolling the escape.
        # A hand-written double-quoted scalar keeps PHYSICAL newlines, and
        # YAML folds those to a single space -- so "A\nB" reinstalled as
        # "A B". A NUL produced a document PyYAML refuses outright. The
        # emitter knows every escape; this function only decides WHETHER.
        #
        # Emitted inside a one-item flow list and unwrapped, so there is no
        # document-end marker to trim off a bare scalar dump.
        return _yaml_flow_list([value])[1:-1]
    return value


def _reads_back_as_itself(value: str) -> bool:
    """Whether the bare scalar parses back to the identical string."""
    try:
        return yaml.safe_load(value) == value
    except yaml.YAMLError:
        return False
