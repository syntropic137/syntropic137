"""Fail when the fitness report lists a stale exception.

A stale exception is a waiver in fitness-exceptions.toml whose debt no longer
exists: the code was fixed and the waiver outlived it. The fitness tool detects
these and prints them, but exits 0, so they scroll past in green runs. Three of
them had accumulated by #1084 - waivers of 20 on functions measuring 11, 8 and 7
against a global limit of 15.

That is worse than clutter. A waiver that outlives its debt is standing
permission to reintroduce the very complexity the gate exists to stop, and the
author who does it is waved through without ever seeing a failure.

Removing a stale waiver is always safe: the tool reports `NowPassing` precisely
because the entity passes the global threshold on its own.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypedDict


class StaleException(TypedDict):
    entity: str
    rule_id: str
    reason: str


def stale_from_report(report: object) -> list[StaleException]:
    """Extract stale exceptions, treating a malformed report as a hard error.

    A missing or misshapen `stale_exceptions` key must not read as "none":
    that would turn a broken report into a silent pass, which is the same
    failure mode this check exists to close.
    """
    if not isinstance(report, dict):
        raise ValueError(f"report is {type(report).__name__}, expected an object")
    if "stale_exceptions" not in report:
        raise ValueError("report has no 'stale_exceptions' key")
    entries = report["stale_exceptions"]
    if not isinstance(entries, list):
        raise ValueError(f"'stale_exceptions' is {type(entries).__name__}, expected a list")
    out: list[StaleException] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"stale exception entry is {type(entry).__name__}, expected an object")
        out.append(
            StaleException(
                entity=str(entry.get("entity", "<unknown>")),
                rule_id=str(entry.get("rule_id", "<unknown>")),
                reason=str(entry.get("reason", "<unknown>")),
            )
        )
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <fitness-report.json>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    try:
        report = json.loads(path.read_text())
    except FileNotFoundError:
        print(f"Fitness report not found: {path}", file=sys.stderr)
        print("The validate step should have written it - did it fail first?", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Fitness report at {path} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    try:
        stale = stale_from_report(report)
    except ValueError as exc:
        print(f"Fitness report at {path} is malformed: {exc}", file=sys.stderr)
        return 2

    if not stale:
        return 0

    plural = "" if len(stale) == 1 else "s"
    print(f"\n{len(stale)} stale exception{plural} in fitness-exceptions.toml:\n", file=sys.stderr)
    for entry in stale:
        print(f"  {entry['entity']} [{entry['rule_id']}]: {entry['reason']}", file=sys.stderr)
    print(
        "\nThese waivers cover debt that no longer exists. Delete the matching\n"
        "entries from fitness-exceptions.toml - the code passes the global\n"
        "threshold without them, which is why the tool reports them as stale.\n"
        "Leaving one in place is standing permission to reintroduce the\n"
        "complexity it was granted for.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
