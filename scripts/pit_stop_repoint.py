"""Repoint a deployed compose file at the syn-api/syn-gateway a pit stop shipped.

Called by scripts/pit_stop.sh at `stage`:

    python3 scripts/pit_stop_repoint.py <tag> <deployed-compose> <staged-compose> [--service gateway]
    python3 scripts/pit_stop_repoint.py --on-tag <tag> <compose> <service>
    python3 scripts/pit_stop_repoint.py --drift <published-compose> <deployed-compose>
    python3 scripts/pit_stop_repoint.py --add-null-keys <published-compose> <deployed-compose> <out>

The second form prints 1 when the compose service <service> (`api` or
`gateway`) has one image line and it names exactly the ref `ship` loaded, else 0. It is the count
the stage and --swap-only prechecks trust, so it reads the image lines the same
way the repoint writes them: a commented-out line, a longer tag that merely
starts with <tag> (`beta.1` vs `beta.10`) or a suffixed one is not on the tag.

The third form exits 1 and prints a unified diff when the deployed compose
differs from the one the shipped ref publishes in anything but image pins, else
exits 0 silently (#1511). A pit stop only repoints pins, so an image whose
startup needs new compose config (a volume, an env var, a proxy policy) would
otherwise be deployed without it and abort on every start. Every image line is
compared by image NAME: the published file says `${SYN_VERSION:-latest}`, a
release-installed host a digest, a hotfixed one a tag, and none of that is drift.

The fourth form handles the one drift that needs no owner (#2154): env keys
the published compose adds as `KEY: null`. A null passthrough forwards only the
host's .env value, which is unset for a key the host has never had, so the
setting's default applies, exactly as on a fresh install. It writes <out> as
the deployed file with exactly those lines inserted where the published file has
them (every other byte, the host's own pins included, kept), prints each added
key on stdout and exits 0. It exits 0 printing nothing, and writes nothing, when
there is no drift. Any other drift (a valued key, a removed or changed line,
a key outside an `environment:` map) exits 1 with the reason on stderr and
writes nothing: that still goes to the owner.

The first form writes the staged compose and prints, on stdout, the name to back the
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

import difflib
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

#: Horizontal whitespace only: `\s` crosses newlines, so a blank line above an
#: image key would start the match there and `_owner` would measure the blank
#: line's indent, not the key's, and pick the wrong service or none.
_IMAGE_LINE = re.compile(r"^(?P<lead>[ \t]*image:[ \t]*[\"']?)(?P<ref>[^\s\"'#]+)", re.MULTILINE)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
#: An env passthrough with no value. Literally `null`: `""`, `~`, `${X}` or a
#: trailing comment is not this shape and stays the owner's.
_NULL_KEY = re.compile(r"(?P<indent>[ \t]+)(?P<key>[A-Z][A-Z0-9_]*):[ \t]*null[ \t]*")
#: A mapping key that opens a nested block: no value, anchor, alias or block scalar.
_PLAIN_PARENT = re.compile(r"[A-Za-z0-9._-]+:")
#: An env map entry this will sit beside: a bare key. A quoted (`'FOO':`),
#: tagged (`!!merge`), merge (`<<`), anchored or aliased key is refused, since
#: the plain spelling of a duplicate or an override could not be told from it.
_BARE_ENTRY = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*:(?:[ \t].*)?")


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


def _unpinned(m: re.Match[str]) -> str:
    path, _, name = m["ref"].partition("@")[0].rpartition("/")
    return m["lead"] + (f"{path}/" if path else "") + name.partition(":")[0]


def _significant(lines: list[str]) -> list[tuple[str, int]]:
    """Each line `drift` compares, pin cut to its repository, with its index in
    `lines`: blank and comment lines are skipped, since neither pins nor
    commentary change what a service runs."""
    return [
        (_IMAGE_LINE.sub(_unpinned, line), i)
        for i, line in enumerate(lines)
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _without_pins(compose: str) -> list[str]:
    """`compose` with every image ref cut to its repository, and without blank
    and comment lines."""
    return [line for line, _ in _significant(compose.splitlines(keepends=True))]


def drift(published: str, deployed: str) -> str:
    """The unified diff from `deployed` to `published`, pins aside; empty when none."""
    return "".join(
        difflib.unified_diff(
            _without_pins(deployed),
            _without_pins(published),
            fromfile="deployed",
            tofile="published",
        )
    )


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _parent(lines: list[str], at: int) -> int:
    """The index of the line `at` sits under: the nearest significant line
    above it that is indented less, or -1."""
    for i in range(at - 1, -1, -1):
        line = lines[i]
        if (
            line.strip()
            and not line.lstrip().startswith("#")
            and _indent(line) < _indent(lines[at])
        ):
            return i
    return -1


def _check_env_line(lines: list[str], at: int, key: str) -> None:
    """Raise unless line `at` is a key of `services.<name>.environment`, reached
    through plain mapping keys only (so never text inside a block scalar such
    as `command: |`), in a map with no merge key and no other `key`."""
    env = _parent(lines, at)
    svc = _parent(lines, env) if env >= 0 else -1
    root = _parent(lines, svc) if svc >= 0 else -1
    chain = [lines[i] for i in (env, svc, root) if i >= 0]
    if (
        len(chain) != 3
        or chain[0].strip() != "environment:"
        or not _PLAIN_PARENT.fullmatch(chain[1].strip())
        or _indent(chain[2]) != 0
        or chain[2].strip() != "services:"
        or _parent(lines, root) != -1
    ):
        raise RepointError(f"{key} is not in a services.<name>.environment: map")
    siblings: list[str] = []
    for line in lines[env + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _indent(line) <= _indent(lines[env]):
            break
        if _indent(line) == _indent(lines[at]):
            if not _BARE_ENTRY.fullmatch(line.strip()):
                raise RepointError(
                    f"{key}'s environment: map has a key that is not bare ({line.strip()}); "
                    "a null could duplicate or override it"
                )
            siblings.append(line.strip().partition(":")[0])
    if siblings.count(key) != 1:
        raise RepointError(f"{key} would be set more than once in its environment: map")


def add_null_keys(published: str, deployed: str) -> tuple[str, tuple[str, ...]]:
    """`deployed` with the `KEY: null` env lines `published` adds, and those keys.

    Raises RepointError unless every difference, pins aside, is such a line."""
    if "\r" in published or "\r" in deployed:
        raise RepointError("a compose file has CR line endings; not rewriting it")
    pub_lines = published.splitlines(keepends=True)
    dep_lines = deployed.splitlines(keepends=True)
    pub, dep = _significant(pub_lines), _significant(dep_lines)
    matcher = difflib.SequenceMatcher(
        None, [s for s, _ in dep], [s for s, _ in pub], autojunk=False
    )
    after: dict[int, list[str]] = {}
    keys: list[str] = []
    for op, i1, _i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        if op != "insert":
            where = dep[i1][1] + 1 if i1 < len(dep) else len(dep_lines)
            raise RepointError(f"deployed line {where} differs from the published compose ({op})")
        if i1 == 0:
            raise RepointError("the published compose adds lines before any it shares")
        for _, j in pub[j1:j2]:
            m = _NULL_KEY.fullmatch(pub_lines[j].rstrip("\r\n"))
            if not m:
                raise RepointError(f"not a KEY: null passthrough: {pub_lines[j].strip()}")
            _check_env_line(pub_lines, j, m["key"])
            keys.append(m["key"])
            after.setdefault(dep[i1 - 1][1], []).append(pub_lines[j])
    out: list[str] = []
    for i, line in enumerate(dep_lines):
        out.append(line)
        if i in after:
            if not line.endswith("\n"):
                out[-1] = line + "\n"
            out.extend(after[i])
    text = "".join(out)
    if drift(published, text):
        raise RepointError("adding the keys did not clear the drift")
    return text, tuple(keys)


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--drift":
        diff = drift(Path(argv[1]).read_text(), Path(argv[2]).read_text())
        print(diff, end="")
        return 1 if diff else 0
    if len(argv) == 4 and argv[0] == "--add-null-keys":
        _, published, deployed, out = argv
        try:
            # Bytes, not read_text(): universal newlines would hide a CRLF file.
            text, keys = add_null_keys(
                Path(published).read_bytes().decode(), Path(deployed).read_bytes().decode()
            )
        except RepointError as e:
            print(f"   cannot add env keys: {e}", file=sys.stderr)
            return 1
        if keys:
            Path(out).write_bytes(text.encode())
            print("\n".join(keys))
        return 0
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
