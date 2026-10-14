"""Repoint a deployed compose file at the syn-api/syn-gateway a pit stop shipped.

Called by scripts/pit_stop.sh at `stage`:

    python3 scripts/pit_stop_repoint.py <tag> <deployed-compose> <staged-compose> [--service gateway]
    python3 scripts/pit_stop_repoint.py --on-tag <tag> <compose> <service>

The second form prints 1 when the compose service <service> (`api` or
`gateway`) has one image line and it names exactly the ref `ship` loaded, else 0. It is the count
the stage and --swap-only prechecks trust, so it reads the image lines the same
way the repoint writes them: a commented-out line, a longer tag that merely
starts with <tag> (`beta.1` vs `beta.10`) or a suffixed one is not on the tag.

It writes the staged compose and prints, on stdout, the name to back the
deployed file up under (empty when every pin is already the shipped ref, so
there is nothing to stage). `--service gateway` repoints the syn-gateway pin
alone and leaves syn-api's exactly as deployed (#1310). Anything it cannot
repoint safely exits 1 with the reason on stderr, and nothing is written.

WHY THIS IS NOT A sed. A host installed from a release pins every image BY
DIGEST (`ghcr.io/syntropic137/syn-api@sha256:<64 hex>`), and the two digests
differ, so there is no single "old pin" to substitute for both services. A
host that was hotfixed carries a different TAG per service, sometimes with no
registry prefix (#1431). Each service is therefore read on its own, and its
whole ref is replaced with the exact ref `ship` loaded, never edited in place:
the images are only in the host's daemon, unpushed, so they have no digest and
no other spelling resolves to them.

BY COMPOSE SERVICE, NOT BY IMAGE NAME. The executor runs the syn-api image in
another role (ADR-072 D1, #1310 1.6), so a compose with it names syn-api twice.
A pit stop recreates `api` and `gateway` only, so only THEIR lines move: an
executor pin moved under a container that was never recreated would claim a
build it is not running, which is drift. The executor's line is left exactly
as deployed until a pit stop that recreates the executor exists.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: The compose services a pit stop recreates, to the image `ship` loads for each.
IMAGES = {"api": "syn-api", "gateway": "syn-gateway"}
#: `--service` as pit_stop.sh spells it, to the compose services it recreates.
#: Never `executor`: no pit stop recreates it yet, so none may move its pin.
SHIPPED = {"all": ("api", "gateway"), "gateway": ("gateway",)}
REGISTRY = "ghcr.io/syntropic137"

_IMAGE_LINE = re.compile(r"^(?P<lead>\s*image:\s*[\"']?)(?P<ref>[^\s\"'#]+)", re.MULTILINE)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class RepointError(Exception):
    """The compose file is not in a shape this can repoint without guessing."""


@dataclass(frozen=True)
class Pin:
    """One service's image ref as the deployed compose spells it."""

    service: str
    ref: str

    @property
    def pin(self) -> str:
        """The digest if there is one, else the tag: `sha256:...` or `v0.33.1`."""
        repository, _, digest = self.ref.partition("@")
        if digest:
            return digest
        name = repository.rsplit("/", 1)[-1]
        return name.partition(":")[2]


@dataclass(frozen=True)
class Repoint:
    old: tuple[Pin, ...]
    text: str
    changed: bool

    @property
    def backup_suffix(self) -> str:
        """The first repointed pin (syn-api's, unless only the gateway was
        shipped), filesystem-safe: `v0.33.1` or `sha256-bf783882d031`."""
        pin = self.old[0].pin
        if _DIGEST.fullmatch(pin):
            return "sha256-" + pin.removeprefix("sha256:")[:12]
        return re.sub(r"[^0-9A-Za-z._-]", "-", pin)


def _image_name(ref: str) -> str:
    return ref.partition("@")[0].rsplit("/", 1)[-1].partition(":")[0]


def _owner(compose: str, at: int) -> str:
    """The compose service an image line at offset `at` belongs to: the nearest
    line above it that is indented less, which is the service's own key."""
    line_start = compose.rfind("\n", 0, at) + 1
    image_line = compose[line_start : compose.find("\n", at) if "\n" in compose[at:] else None]
    indent = len(image_line) - len(image_line.lstrip())
    for line in reversed(compose[:line_start].splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(line) - len(line.lstrip()) < indent:
            return stripped.partition(":")[0].strip("\"'")
    return ""


def _lines_of(compose: str, service: str) -> list[re.Match[str]]:
    """The image lines of compose service `service` (`api`, `gateway`)."""
    return [m for m in _IMAGE_LINE.finditer(compose) if _owner(compose, m.start()) == service]


def repoint(compose: str, tag: str, services: tuple[str, ...] = SHIPPED["all"]) -> Repoint:
    """Point each of `services` at `REGISTRY/<its image>:<tag>`, or raise RepointError."""
    old: list[Pin] = []
    for service in services:
        image = IMAGES[service]
        found = _lines_of(compose, service)
        if len(found) != 1:
            raise RepointError(f"expected one image line for service {service}, found {len(found)}")
        pin = Pin(image, found[0]["ref"])
        if _image_name(pin.ref) != image:
            raise RepointError(f"service {service} runs {pin.ref}, not {image}")
        if "$" in pin.ref:
            raise RepointError(
                f"{image} is pinned by a variable ({pin.ref}); this is not a release compose"
            )
        if not pin.pin:
            raise RepointError(f"{image} is not pinned to a tag or a digest ({pin.ref})")
        old.append(pin)

    def new_ref(m: re.Match[str]) -> str:
        service = _owner(compose, m.start())
        if service in services:
            return m["lead"] + f"{REGISTRY}/{IMAGES[service]}:{tag}"
        return m[0]

    text = _IMAGE_LINE.sub(new_ref, compose)
    return Repoint(old=tuple(old), text=text, changed=text != compose)


def on_tag(compose: str, tag: str, service: str) -> bool:
    """Whether compose service `service`'s one image line names
    `REGISTRY/<its image>:<tag>` exactly. Compared whole, never as a pattern.

    A digest-qualified `...:<tag>@sha256:...` is NOT on the tag: Docker
    resolves a tag-plus-digest reference by the digest alone, and the image
    `ship` loaded is unpushed, so no digest in a compose file is proven to be
    it. The repoint writes the bare ref, so a staged file never has one."""
    found = {m["ref"] for m in _lines_of(compose, service)}
    return found == {f"{REGISTRY}/{IMAGES[service]}:{tag}"}


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[0] == "--on-tag":
        _, tag, compose, svc = argv
        print(1 if svc in IMAGES and on_tag(Path(compose).read_text(), tag, svc) else 0)
        return 0
    service = "all"
    if len(argv) == 5 and argv[3] == "--service":
        service, argv = argv[4], argv[:3]
    if len(argv) != 3 or service not in SHIPPED:
        print(__doc__, file=sys.stderr)
        return 2
    tag, deployed, staged = argv
    try:
        result = repoint(Path(deployed).read_text(), tag, SHIPPED[service])
    except RepointError as e:
        print(f"   cannot repoint: {e}", file=sys.stderr)
        return 1
    for pin in result.old:
        print(f"   {pin.service}: {pin.ref} -> {REGISTRY}/{pin.service}:{tag}", file=sys.stderr)
    Path(staged).write_text(result.text)
    print(result.backup_suffix if result.changed else "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
