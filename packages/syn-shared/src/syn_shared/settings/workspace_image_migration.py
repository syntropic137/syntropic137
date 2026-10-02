"""Move a copied default workspace image in ``.env`` to the current default (#1398).

``.env.example`` ships the default digest for ``SYN_WORKSPACE_DOCKER_IMAGE``,
and a value in ``.env`` overrides the code default. So an operator who copied
the example keeps running the image of the day they installed, through every
later pin bump. ``selfhost-update`` runs this after pulling: a value that is a
previously shipped default (``PREVIOUS_DEFAULT_WORKSPACE_IMAGES``) is replaced
with ``DEFAULT_WORKSPACE_IMAGE``; any other value is a deliberate override and
is never touched. Every outcome is printed.

Usage: ``python -m syn_shared.settings.workspace_image_migration [ENV_FILE]``
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_IMAGE,
    PREVIOUS_DEFAULT_WORKSPACE_IMAGES,
)

ENV_VAR = "SYN_WORKSPACE_DOCKER_IMAGE"

_ASSIGNMENT = re.compile(
    rf"""^(?P<head>\s*(?:export\s+)?{ENV_VAR}\s*=\s*)"""
    r"""(?P<quote>['"]?)(?P<value>[^'"\s#]*)(?P=quote)(?P<tail>.*)$"""
)


class MigrationOutcome(StrEnum):
    MIGRATED = "migrated"  # a previously shipped default, moved to the current one
    CURRENT = "current"  # already the current default
    CUSTOM = "custom"  # an operator's own image: left alone
    ABSENT = "absent"  # not set; the code default applies


@dataclass(frozen=True)
class Migration:
    outcome: MigrationOutcome
    text: str
    previous: str | None = None


def migrate_text(text: str) -> Migration:
    """Rewrite every assignment of a previously shipped default; keep the rest."""
    previous = frozenset(PREVIOUS_DEFAULT_WORKSPACE_IMAGES)
    lines = text.splitlines(keepends=True)
    outcome = MigrationOutcome.ABSENT
    replaced: str | None = None
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        match = _ASSIGNMENT.match(body)
        if match is None:
            continue
        value = match["value"]
        if value in previous:
            ending = line[len(body) :]
            lines[index] = (
                f"{match['head']}{match['quote']}{DEFAULT_WORKSPACE_IMAGE}"
                f"{match['quote']}{match['tail']}{ending}"
            )
            outcome, replaced = MigrationOutcome.MIGRATED, value
        elif outcome is not MigrationOutcome.MIGRATED:
            outcome = (
                MigrationOutcome.CURRENT
                if value == DEFAULT_WORKSPACE_IMAGE
                else MigrationOutcome.CUSTOM
            )
    return Migration(outcome=outcome, text="".join(lines), previous=replaced)


def migrate_file(path: Path) -> Migration:
    if not path.is_file():
        return Migration(outcome=MigrationOutcome.ABSENT, text="")
    original = path.read_text()
    result = migrate_text(original)
    if result.text != original:
        path.write_text(result.text)
    return result


def describe(result: Migration, path: Path) -> str:
    if result.outcome is MigrationOutcome.MIGRATED:
        return (
            f"  ⬆️  {ENV_VAR} in {path}: previously shipped default\n"
            f"      {result.previous}\n"
            f"      -> {DEFAULT_WORKSPACE_IMAGE}"
        )
    if result.outcome is MigrationOutcome.CUSTOM:
        return (
            f"  • {ENV_VAR} in {path} is a custom image; left unchanged "
            f"(current default: {DEFAULT_WORKSPACE_IMAGE})"
        )
    if result.outcome is MigrationOutcome.CURRENT:
        return f"  ✅ {ENV_VAR} in {path} is the current default"
    return f"  ✅ {ENV_VAR} not set in {path}; the code default applies"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0] if args else ".env")
    print(describe(migrate_file(path), path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
