"""Guard: nothing in this repo may publish a container port to every interface.

WHY THIS EXISTS. A sibling repo's `just pg-up` ran `docker run ... -p 5433:5432`,
which binds 0.0.0.0. On a laptop behind NAT that is invisible. On a host with a
public IP it put a superuser Postgres on the internet, and `COPY ... FROM
PROGRAM` turned that into remote code execution in 35 minutes. The host mined
crypto for 21 days on about half its cores before anyone noticed.

Two things make this worse than it sounds:

  1. A host firewall does NOT save you. Docker's NAT rewrites the destination
     before the routing decision, so a published port never traverses the INPUT
     chain that ufw/pf manages. The compromised host had ufw enabled,
     default-deny, the whole time.
  2. There is no patch. `COPY ... FROM PROGRAM` is deliberate Postgres
     behaviour: to Postgres, a superuser IS the OS account. An exposed database
     is not "a database at risk", it is a shell at risk.

THE RULE: every publish binds a loopback host interface, either literally
(`127.0.0.1:5432:5432`) or through a variable that DEFAULTS to one
(`${SYN_ENV_BIND:-127.0.0.1}:`).

WHY THIS IS PYTHON AND NOT AWK. The first version of this gate inferred safety
by COUNTING COLONS in the text of each line: two or more colons meant "the
first field must be the interface". That is a guess about syntax standing in
for a fact about semantics, and it passed the exact vulnerability the gate
exists to prevent. `0.0.0.0:15432:5432` has two colons. So does `[::]:5432:5432`
and `0.0.0.0:15432-15434:5432-5434`. Meanwhile the state machine that found the
entries matched only a physical line reading exactly `ports:`, so flow style
(`ports: ["5432:5432"]`), a trailing comment (`ports: # public`), a quoted key
(`"ports":`) and a YAML alias were never scanned at all, and long syntax was
rejected only by the accident of `target:` having one colon - which also
rejected the SAFE long form that spells out `host_ip: 127.0.0.1`.

So this loads each compose document with a YAML parser, which normalises flow
collections, quoted keys and aliases before any rule runs, walks
`services.*.ports[]`, and decides on what the entry MEANS: which interface does
this bind? Nothing here counts a character.

WHAT THIS GATE DOES NOT PROMISE. It resolves `${...}` with every variable
UNSET, so its guarantee is about DEFAULTS. `${SYN_ENV_BIND:-127.0.0.1}` binds
loopback here and binds 0.0.0.0 for an operator who exports
`SYN_ENV_BIND=0.0.0.0`. Forbidding interpolation outright would be a stronger
guarantee, but it would also delete the supported way to run selfhost behind a
reverse proxy, so instead every variable that can flip a bind public must be
named in DECLARED_OPERATOR_BINDS below, the run reports how large that surface
is, and a new undeclared one fails.

SCOPE is what actually starts containers: compose files under docker/ and
infra/, the justfile, and scripts/. Prose in docs and READMEs is out of scope on
purpose. .github/workflows is out of scope too: GitHub Actions `services.ports`
has no interface syntax to name, and those runners are ephemeral and
network-isolated.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

#: Variables an operator is allowed to point somewhere other than loopback,
#: because publishing selfhost behind a reverse proxy is a supported
#: deployment and not an accident. Each entry widens the blast radius of a
#: single `export`, so adding one is a security decision and is meant to show
#: up in review rather than pass silently.
DECLARED_OPERATOR_BINDS = frozenset({"SYN_ENV_BIND", "SYN_GATEWAY_BIND"})

#: This gate's own fixtures are publicly-binding on purpose - they are the
#: spellings the previous version waved through. They are excluded from
#: SCANNING, not from checking: `scripts/tests/test_no_public_ports.py` asserts
#: the exact verdict for every entry in them on every test run. Note that git
#: pathspecs match across `/`, so `scripts/*.sh` reaches them without this.
FIXTURE_DIR = Path("scripts/tests/fixtures/no_public_ports")

#: Compose short syntax lets the protocol ride along on the container port
#: (`6060:6060/udp`). It never affects which interface is bound.
_PROTOCOL_SUFFIX = re.compile(r"/[A-Za-z]+$")

#: `${NAME}`, `${NAME:-default}`, `${NAME-default}`, `${NAME:?err}`,
#: `${NAME:+alt}` and bare `$NAME`, which is the whole of Compose
#: interpolation that can appear in a port mapping.
_BRACED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-+?])([^{}]*))?\}")
_BARE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")

#: `$$` is Compose's escape for a literal `$`; it is not a variable.
_ESCAPED_DOLLAR = "\x00SYN_DOLLAR\x00"


@dataclass(frozen=True)
class Publish:
    """One port publication, with enough provenance to point a human at it.

    `spec` is the short-syntax string as written, or None for long syntax, in
    which case `host_ip` carries the `host_ip:` value (None when the key is
    absent, which is what makes long syntax bind everything).
    """

    file: str
    line: int
    shown: str
    spec: str | None = None
    host_ip: str | None = None
    long_form: bool = False


@dataclass(frozen=True)
class Finding:
    """A publish that reaches beyond loopback, and why."""

    file: str
    line: int
    shown: str
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} -- {self.shown}: {self.reason}"


def interpolate(text: str, env: dict[str, str]) -> str:
    """Resolve Compose `${...}` against `env`, treating absent names as unset.

    Unset with no default yields the empty string, exactly as Compose does, so
    `${BIND}:5432:5432` resolves to `:5432:5432` and is then judged on what it
    means rather than on how it was spelled.
    """
    text = text.replace("$$", _ESCAPED_DOLLAR)

    def braced(match: re.Match[str]) -> str:
        name, operator, argument = match.group(1), match.group(2), match.group(3) or ""
        value = env.get(name)
        if operator in (":-", ":?") and not value:
            return argument if operator == ":-" else ""
        if operator in ("-", "?") and value is None:
            return argument if operator == "-" else ""
        if operator == ":+":
            return argument if value else ""
        if operator == "+":
            return argument if value is not None else ""
        return value or ""

    text = _BRACED.sub(braced, text)
    text = _BARE.sub(lambda m: env.get(m.group(1), ""), text)
    return text.replace(_ESCAPED_DOLLAR, "$")


def variable_names(text: str) -> list[str]:
    """Every variable name `text` interpolates, in order of appearance."""
    names: list[str] = []
    for name in _BRACED.findall(text.replace("$$", _ESCAPED_DOLLAR)):
        if name[0] not in names:
            names.append(name[0])
    for name in _BARE.findall(_BRACED.sub("", text.replace("$$", _ESCAPED_DOLLAR))):
        if name not in names:
            names.append(name)
    return names


def split_short_syntax(spec: str) -> tuple[str | None, str, str]:
    """Split resolved Compose short syntax into (host_ip, published, target).

    `host_ip` is None when the mapping has no host-interface field at all,
    which is a different defect from naming an empty or public one and gets a
    different message. Splitting from the RIGHT is what makes this work for
    every spelling at once: the container port is always last, so a bracketed
    IPv6 host, a port range and a bare container port all fall out of the same
    rule instead of each needing a case.
    """
    spec = _PROTOCOL_SUFFIX.sub("", spec.strip())

    if spec.startswith("["):
        close = spec.find("]")
        if close != -1:
            rest = spec[close + 1 :].lstrip(":").split(":")
            return spec[1:close], *_last_two(rest)

    fields = spec.split(":")
    if len(fields) < 3:
        return None, *_last_two(fields)
    return ":".join(fields[:-2]), fields[-2], fields[-1]


def _last_two(fields: list[str]) -> tuple[str, str]:
    if len(fields) < 2:
        return "", fields[0] if fields else ""
    return fields[-2], fields[-1]


def binds_loopback(host_ip: str) -> bool:
    """Is `host_ip` an address that only the host itself can reach?

    Anything this cannot prove is loopback is not loopback. That is the whole
    rule, and it is why `0.0.0.0` and `::` need no special case: they are
    simply two of the infinitely many addresses that are not 127.0.0.0/8 or
    ::1. A gate written as a blocklist of those two would still wave through
    a LAN address, which is the same defect one step further out.
    """
    host_ip = host_ip.strip()
    if host_ip.startswith("[") and host_ip.endswith("]"):
        host_ip = host_ip[1:-1]
    if host_ip == "localhost":
        return True
    try:
        return ipaddress.ip_address(host_ip).is_loopback
    except ValueError:
        return False


def reject_reason(publish: Publish, env: dict[str, str]) -> str | None:
    """Why this publish reaches beyond loopback under `env`, or None if it does not."""
    if publish.long_form:
        if publish.host_ip is None:
            return "long syntax with no host_ip binds every interface"
        return _reason_for_host_ip(interpolate(publish.host_ip, env))

    resolved = interpolate(publish.spec or "", env)
    if _BRACED.search(resolved) or _BARE.search(resolved):
        return f"unresolved interpolation in {resolved!r}; this gate cannot prove where it binds"

    host_ip, _, _ = split_short_syntax(resolved)
    if host_ip is None:
        if ":" not in resolved:
            return "no host port at all, so Docker picks a random one on every interface"
        return "names a host port but no host interface"
    return _reason_for_host_ip(host_ip)


def _reason_for_host_ip(host_ip: str) -> str | None:
    if not host_ip.strip():
        return "empty host interface binds every interface"
    if not binds_loopback(host_ip):
        return f"host interface {host_ip!r} is not loopback"
    return None


def host_ip_variables(publish: Publish) -> list[str]:
    """The variables that land in the host-interface field of this publish.

    A port variable is not an interface variable, so probing every name would
    blame the wrong one. Resolving all of them to distinct markers in a single
    pass and then asking which markers ended up in the host-IP field answers
    that exactly, without depending on where the `${...}` sits in the text.
    """
    if publish.long_form:
        return variable_names(publish.host_ip or "")

    spec = publish.spec or ""
    names = variable_names(spec)
    markers = {name: f"synmark{index}" for index, name in enumerate(names)}
    host_ip, _, _ = split_short_syntax(interpolate(spec, markers))
    return [name for name in names if markers[name] in (host_ip or "")]


def evaluate(publishes: list[Publish]) -> tuple[int, list[str]]:
    """Judge every publish and render the verdict. Returns (exit code, lines)."""
    findings: list[Finding] = []
    overridable: list[tuple[Publish, str]] = []

    for publish in publishes:
        reason = reject_reason(publish, {})
        if reason is not None:
            findings.append(Finding(publish.file, publish.line, publish.shown, reason))
            continue
        for name in host_ip_variables(publish):
            if any(reject_reason(publish, {name: hostile}) for hostile in ("0.0.0.0", "::")):
                overridable.append((publish, name))

    for publish, name in overridable:
        if name in DECLARED_OPERATOR_BINDS:
            continue
        findings.append(
            Finding(
                publish.file,
                publish.line,
                publish.shown,
                f"${{{name}}} chooses the host interface but is not a declared operator "
                f"override; hard-wire a loopback address or add {name} to "
                f"DECLARED_OPERATOR_BINDS in {Path(__file__).name} so the choice is reviewed",
            )
        )

    if findings:
        ordered = sorted(findings, key=lambda f: (f.file, f.line, f.reason))
        lines = [f"no_public_ports: {finding}" for finding in ordered]
        lines.append(
            f"no_public_ports: FAIL. See the comment at the top of scripts/{Path(__file__).name}."
        )
        return 1, lines

    lines = [
        f"no_public_ports: ok ({len(publishes)} publishes bind loopback with every variable unset)"
    ]
    if overridable:
        levers = sorted({name for _, name in overridable})
        lines.append(
            f"no_public_ports: this checks DEFAULTS. {len(overridable)} of them bind every "
            f"interface if an operator exports {', '.join(f'{n}=0.0.0.0' for n in levers)}."
        )
    return 0, lines


def publishes_in_compose(path: str, text: str) -> list[Publish]:
    """Every `services.*.ports[]` entry in a compose document.

    Walking the parsed node graph rather than the text is the point: the parser
    has already turned flow style, quoted keys, aliases and multi-line block
    entries into the same shape, so there is one code path instead of one per
    spelling, and the nodes still carry the line numbers a human needs.
    """
    found: list[Publish] = []
    for document in yaml.compose_all(text):
        for _, service in _mapping_items(_child(document, "services")):
            for entry in _sequence(_child(service, "ports")):
                found.append(_publish_from_node(path, entry))
    return found


def _publish_from_node(path: str, node: yaml.Node) -> Publish:
    line = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        fields = dict(_mapping_items(node))
        host_ip = fields.get("host_ip")
        shown = "long syntax entry"
        if (target := fields.get("target")) is not None and isinstance(target, yaml.ScalarNode):
            shown = f"long syntax entry target {target.value}"
        return Publish(
            path,
            line,
            shown,
            host_ip=host_ip.value if isinstance(host_ip, yaml.ScalarNode) else None,
            long_form=True,
        )
    value = node.value if isinstance(node, yaml.ScalarNode) else str(node)
    return Publish(path, line, repr(value), spec=value)


def _child(node: yaml.Node | None, key: str) -> yaml.Node | None:
    for name, value in _mapping_items(node):
        if name == key:
            return value
    return None


def _mapping_items(node: yaml.Node | None) -> list[tuple[str, yaml.Node]]:
    if not isinstance(node, yaml.MappingNode):
        return []
    return [(k.value, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)]


def _sequence(node: yaml.Node | None) -> list[yaml.Node]:
    return list(node.value) if isinstance(node, yaml.SequenceNode) else []


#: `-p`/`--publish` and its argument, with the quoting the shell would strip.
#: The quotes are why the first version missed `-p "${PROXY_PORT}:8080"`: it
#: required the argument to START with a digit or a `$`.
_PUBLISH_FLAG = re.compile(r"""(?:^|\s)(?:-p|--publish)[=\s]+("[^"]*"|'[^']*'|\S+)""")

#: `mkdir -p workspaces` and `cargo build -p aps-cli` are also `-p`. A port
#: mapping either contains a colon and starts somewhere an address or a
#: variable can start, or is a bare container port.
_LOOKS_LIKE_A_PORT = re.compile(r"^(?:[\[$0-9].*:.*|\d+(?:-\d+)?)$")


def publishes_in_shell(path: str, text: str) -> list[Publish]:
    """Every `docker run -p ...` style publish in a shell script or justfile."""
    found: list[Publish] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _PUBLISH_FLAG.finditer(line):
            argument = match.group(1).strip("\"'")
            if _LOOKS_LIKE_A_PORT.match(argument):
                found.append(Publish(path, number, repr(argument), spec=argument))
    return found


def tracked_files(root: Path) -> tuple[list[Path], list[Path]]:
    """(compose files, shell files) that git tracks, as the gate's scope defines them."""
    listed = subprocess.run(
        [
            "git",
            "ls-files",
            "docker/*.yml",
            "docker/*.yaml",
            "docker/**/*.yml",
            "docker/**/*.yaml",
            "infra/**/*.yml",
            "infra/**/*.yaml",
            "scripts/*.sh",
            "justfile",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    paths = [Path(name) for name in listed if (root / name).is_file()]
    paths = [p for p in paths if FIXTURE_DIR not in p.parents]
    compose = [p for p in paths if p.suffix in (".yml", ".yaml")]
    shell = [p for p in paths if p.suffix == ".sh" or p.name == "justfile"]
    return compose, shell


def collect(root: Path) -> list[Publish]:
    """Every publish in scope, from both compose files and shell."""
    compose_files, shell_files = tracked_files(root)
    found: list[Publish] = []
    for path in compose_files:
        text = (root / path).read_text()
        try:
            found.extend(publishes_in_compose(str(path), text))
        except yaml.YAMLError as error:
            raise SystemExit(f"no_public_ports: cannot parse {path}: {error}") from error
    for path in shell_files:
        found.extend(publishes_in_shell(str(path), (root / path).read_text()))
    return found


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    code, lines = evaluate(collect(root))
    for line in lines:
        print(line, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
