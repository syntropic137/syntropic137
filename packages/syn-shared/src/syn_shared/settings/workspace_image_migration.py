"""Move copied workspace-image defaults in ``.env`` to the current defaults (#1398).

``.env.example`` ships the default for two settings that must move together
when the image publisher changes:

- ``SYN_WORKSPACE_DOCKER_IMAGE``: the workspace image digest.
- ``SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP``: the cosign signer identity
  that image must carry.

A value in ``.env`` overrides the code default, so an operator who copied the
example keeps the values of the day they installed through every later bump,
and a stale identity fails image verification once the pins name images from a
new publisher. ``selfhost-update`` runs this after pulling: a value that is a
previously shipped default is replaced with the current default; any other
value is a deliberate override and is never touched. Every outcome is printed.

Usage: ``python -m syn_shared.settings.workspace_image_migration [ENV_FILE]``
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from syn_shared.env_constants import (
    ENV_SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP,
    ENV_SYN_WORKSPACE_DOCKER_IMAGE,
)
from syn_shared.settings.image_verification import (
    PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS,
    WORKSPACE_IMAGE_IDENTITY_REGEXP,
)
from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_IMAGE,
    PINNED_DIGESTS,
    PREVIOUS_DEFAULT_WORKSPACE_IMAGES,
    workspace_image_ref,
)

#: Kept for callers that name the image variable through this module.
ENV_VAR = ENV_SYN_WORKSPACE_DOCKER_IMAGE


@dataclass(frozen=True)
class MigrationRule:
    """One ``.env`` variable whose previously shipped defaults follow the current one."""

    env_var: str
    current: str
    previous: tuple[str, ...]
    #: What a value that is neither current nor previous is, in operator words.
    custom_label: str

    def assignment(self) -> re.Pattern[str]:
        return re.compile(
            rf"""^(?P<head>\s*(?:export\s+)?{re.escape(self.env_var)}\s*=\s*)"""
            r"""(?P<quote>['"]?)(?P<value>[^'"\s#]*)(?P=quote)(?P<tail>.*)$"""
        )


WORKSPACE_IMAGE_RULE: Final = MigrationRule(
    env_var=ENV_SYN_WORKSPACE_DOCKER_IMAGE,
    current=DEFAULT_WORKSPACE_IMAGE,
    previous=PREVIOUS_DEFAULT_WORKSPACE_IMAGES,
    custom_label="a custom image",
)

IMAGE_IDENTITY_RULE: Final = MigrationRule(
    env_var=ENV_SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP,
    current=WORKSPACE_IMAGE_IDENTITY_REGEXP,
    previous=PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS,
    custom_label="a custom signer identity",
)


class MigrationOutcome(StrEnum):
    MIGRATED = "migrated"  # a previously shipped default, moved to the current one
    CURRENT = "current"  # already the current default
    CUSTOM = "custom"  # an operator's own value: left alone
    ABSENT = "absent"  # not set; the code default applies


@dataclass(frozen=True)
class Migration:
    outcome: MigrationOutcome
    text: str
    previous: str | None = None
    #: The value now in effect, when the variable is set.
    value: str | None = None


def migrate_text(text: str, rule: MigrationRule = WORKSPACE_IMAGE_RULE) -> Migration:
    """Rewrite every assignment of a previously shipped default; keep the rest."""
    previous = frozenset(rule.previous)
    pattern = rule.assignment()
    lines = text.splitlines(keepends=True)
    outcome = MigrationOutcome.ABSENT
    replaced: str | None = None
    effective: str | None = None
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        match = pattern.match(body)
        if match is None:
            continue
        value = match["value"]
        if value in previous:
            ending = line[len(body) :]
            lines[index] = (
                f"{match['head']}{match['quote']}{rule.current}"
                f"{match['quote']}{match['tail']}{ending}"
            )
            outcome, replaced, effective = MigrationOutcome.MIGRATED, value, rule.current
            continue
        # The last assignment wins, as it does for the dotenv reader.
        effective = value
        if outcome is not MigrationOutcome.MIGRATED:
            outcome = MigrationOutcome.CURRENT if value == rule.current else MigrationOutcome.CUSTOM
    return Migration(outcome=outcome, text="".join(lines), previous=replaced, value=effective)


def migrate_file(path: Path, rule: MigrationRule = WORKSPACE_IMAGE_RULE) -> Migration:
    if not path.is_file():
        return Migration(outcome=MigrationOutcome.ABSENT, text="")
    # newline="" on both sides: a CRLF .env keeps its line endings, so the
    # rewrite changes exactly the migrated value and nothing else.
    with path.open(encoding="utf-8", newline="") as handle:
        original = handle.read()
    result = migrate_text(original, rule)
    if result.text != original:
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(result.text)
    return result


def describe(result: Migration, path: Path, rule: MigrationRule = WORKSPACE_IMAGE_RULE) -> str:
    name = rule.env_var
    if result.outcome is MigrationOutcome.MIGRATED:
        return (
            f"  ⬆️  {name} in {path}: previously shipped default\n"
            f"      {result.previous}\n"
            f"      -> {rule.current}"
        )
    if result.outcome is MigrationOutcome.CUSTOM:
        return (
            f"  • {name} in {path} is {rule.custom_label}; left unchanged "
            f"(current default: {rule.current})"
        )
    if result.outcome is MigrationOutcome.CURRENT:
        return f"  ✅ {name} in {path} is the current default"
    return f"  ✅ {name} not set in {path}; the code default applies"


def stale_default_message(value: str, rule: MigrationRule) -> str | None:
    """Name the variable to fix when ``value`` is a default an older release shipped.

    ``None`` for the current default or an operator's own value: those are not
    stale, and an override is never second-guessed.
    """
    if value not in rule.previous:
        return None
    return (
        f"{rule.env_var} is '{value}', a default shipped by an older release; "
        f"this release defaults to '{rule.current}'. Remove {rule.env_var} from "
        "your .env to use the default, or run `just selfhost-update`, which "
        "migrates it."
    )


def image_is_custom(image: str) -> bool:
    """True for an image this release neither pins nor ever shipped as the default.

    Such an image may come from another publisher (an agentic-primitives
    rollback digest), so its signer identity is the operator's call: a
    previously shipped identity next to it is not evidence of staleness.
    """
    pinned = {workspace_image_ref(provider) for provider in PINNED_DIGESTS}
    return (
        image != WORKSPACE_IMAGE_RULE.current
        and image not in pinned
        and image not in WORKSPACE_IMAGE_RULE.previous
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0] if args else ".env")
    image = migrate_file(path, WORKSPACE_IMAGE_RULE)
    print(describe(image, path, WORKSPACE_IMAGE_RULE))
    # The identity names the publisher of the image. With a custom image (for
    # example a pinned agentic-primitives digest for rollback) a shipped
    # identity may be the one that image needs, so moving it would both break
    # verification and silently change which publisher is trusted.
    if image.value is not None and image_is_custom(image.value):
        print(
            f"  • {IMAGE_IDENTITY_RULE.env_var} in {path} left unchanged: "
            f"{WORKSPACE_IMAGE_RULE.env_var} is a custom image, and the identity "
            "must match its publisher"
        )
        return 0
    print(describe(migrate_file(path, IMAGE_IDENTITY_RULE), path, IMAGE_IDENTITY_RULE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
