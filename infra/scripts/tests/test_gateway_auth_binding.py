"""Binding the gateway off loopback must not be possible without auth (#1022).

``SYN_GATEWAY_BIND`` moves the host address of container port 80, and port 80
was unconditionally unauthenticated: ``SYN_API_PASSWORD`` only ever guarded port
8081, which the published stack never publishes to the host. So an operator
could set a password, bind the gateway to a Tailscale address, and serve the
dashboard and the whole API to that network with nothing asking for credentials
-- which is what was observed live on the Mini before this was fixed.

The decision now lives in one place, the gateway entrypoint, under one rule: a
listener reachable from beyond this host requires Basic Auth. These tests drive
the real script rather than reading it, because the failure mode being guarded
is a *behavioural* one -- and they check the two hops the value has to survive
after the entrypoint decides:

* the compose files must pass ``SYN_GATEWAY_BIND`` into the container, since a
  container cannot observe its own port mapping; and
* ``nginx.conf``'s port 80 server block must actually ``include`` the file the
  decision is written to. Generating a correct stanza nobody includes would
  leave the port exactly as exposed as before while every test on either end
  passed.

Having a correct rule is not the same as having it reach every stack, and #1148
is what that difference costs. The first hop above was checked against a hand-
written list of two compose files. The on-demand stack (``just env-up``)
published port 80 through a variable of its own, never passed it in, and
hard-wired ``SYN_API_PASSWORD=`` so no password could be set on that path at
all -- so ``SYN_ENV_BIND=0.0.0.0`` served the dashboard and the whole API to
every interface, with every test in this file green, because that file was not
on the list.

So the compose checks below discover their subjects instead of being told them,
and the last two build the unsafe combination end to end for each one: set the
variable an operator would set, resolve the compose file the way docker
resolves it, hand the result to the real entrypoint, and require a refusal.
Asserting the safe default would have passed against the broken code.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from scripts.no_public_ports import binds_loopback, interpolate, variable_names

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEWAY_IMAGE = _REPO_ROOT / "infra" / "docker" / "images" / "gateway"
_ENTRYPOINT = _GATEWAY_IMAGE / "docker-entrypoint.sh"
_NGINX_CONF = _GATEWAY_IMAGE / "nginx.conf"

#: TEST-NET-3 (RFC 5737). Cannot be a default, a LAN address, or anything a
#: generator could produce on its own, so seeing it act as "exposed" proves the
#: value travelled rather than a default being asserted in its own direction.
_EXPOSED_ADDRESS = "203.0.113.7"

_PASSWORD = "correct-horse-battery-staple"

_AUTH_ON = 'auth_basic "Syntropic137";'
_AUTH_OFF = "auth_basic off;"


# ---------------------------------------------------------------------------
# Driving the real entrypoint
# ---------------------------------------------------------------------------


def _run_entrypoint_with(
    workdir: Path, container_env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run the gateway entrypoint as a container holding `container_env` would.

    ``htpasswd`` ships in the image (apache2-utils) but not on a dev machine or
    in CI, and what it writes is irrelevant here -- only whether nginx is told
    to consult it. Stubbing it keeps these tests dependency-free rather than
    skipping, and a check that skips is a check that cannot fail.

    Takes the whole environment rather than named arguments because the tests
    at the bottom of this file do not know what a compose file put there: they
    resolve it out of the YAML and hand over whatever comes back, which is the
    only way to catch a variable the file forgot to pass.
    """
    bin_dir = workdir / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "htpasswd"
    stub.write_text('#!/bin/sh\nprintf "stub\\n" > "$2"\n')
    stub.chmod(0o755)

    return subprocess.run(
        ["sh", str(_ENTRYPOINT)],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "AUTH_DIR": str(workdir / "auth"),
            **container_env,
        },
        check=False,
    )


def _run_entrypoint(
    workdir: Path, *, bind: str | None, password: str
) -> subprocess.CompletedProcess[str]:
    """The rule tests below state a bind and a password and care about nothing
    else; spelling that as a dict at each of them would bury what varies."""
    env = {"SYN_API_PASSWORD": password}
    if bind is not None:
        env["SYN_GATEWAY_BIND"] = bind
    return _run_entrypoint_with(workdir, env)


def _generated(workdir: Path) -> dict[str, str]:
    """The nginx snippets the entrypoint wrote, by file name.

    The per-run ``AUTH_DIR`` is rewritten back to the path the image uses, so
    two runs differ only where the entrypoint's decisions differ rather than
    where pytest put the temp directory.
    """
    auth_dir = workdir / "auth"
    return {
        path.name: path.read_text().replace(str(auth_dir), _default_auth_dir())
        for path in sorted(auth_dir.iterdir())
        if path.suffix == ".conf"
    }


def _listener_auth(workdir: Path, listen_port: str) -> str:
    """The auth stanza applied to one listener.

    Identified structurally rather than by name: the shared ``locations.conf``
    is included by both server blocks, so the snippet unique to a block is that
    listener's own auth policy. Renaming the generated files does not break
    this; failing to include one does, which is the point.
    """
    conf = _NGINX_CONF.read_text()
    other_port = "8081" if listen_port == "80" else "80"
    only_here = _includes(_server_block(conf, listen_port)) - _includes(
        _server_block(conf, other_port)
    )

    generated = _generated(workdir)
    names = [name for name in generated if f"{_default_auth_dir()}/{name}" in only_here]
    assert len(names) == 1, (
        f"expected the port {listen_port} block to include exactly one generated auth "
        f"snippet of its own, got {names} from {only_here}"
    )
    return generated[names[0]]


# ---------------------------------------------------------------------------
# Reading nginx.conf
# ---------------------------------------------------------------------------


def _server_block(conf: str, listen_port: str) -> str:
    """The `server { ... }` block that declares `listen <listen_port>;`."""
    for match in re.finditer(r"^server\s*\{", conf, re.MULTILINE):
        depth = 0
        for index in range(match.start(), len(conf)):
            if conf[index] == "{":
                depth += 1
            elif conf[index] == "}":
                depth -= 1
                if depth == 0:
                    block = conf[match.start() : index + 1]
                    if f"listen {listen_port};" in block:
                        return block
                    break
    raise AssertionError(f"nginx.conf has no server block listening on {listen_port}")


def _includes(block: str) -> set[str]:
    return set(re.findall(r"^\s*include\s+(\S+);", block, re.MULTILINE))


def _default_auth_dir() -> str:
    """Where the entrypoint writes when AUTH_DIR is not overridden."""
    match = re.search(r'^AUTH_DIR="\$\{AUTH_DIR:-([^}]+)\}"', _ENTRYPOINT.read_text(), re.MULTILINE)
    assert match, "entrypoint no longer declares a default AUTH_DIR"
    return match.group(1)


# ---------------------------------------------------------------------------
# The rule: reachable beyond this host means authenticated
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_binding_off_loopback_without_a_password_refuses_to_start(tmp_path: Path) -> None:
    """The fix. Previously this combination served the API to the network."""
    result = _run_entrypoint(tmp_path, bind=_EXPOSED_ADDRESS, password="")

    assert result.returncode != 0, (
        f"the gateway started with an unauthenticated, network-reachable port 80:\n{result.stdout}"
    )
    assert _EXPOSED_ADDRESS in result.stderr, "the error must name the bind that caused it"
    assert "SYN_API_PASSWORD" in result.stderr, "the error must name the way out"


@pytest.mark.unit
def test_binding_off_loopback_with_a_password_authenticates_the_published_port(
    tmp_path: Path,
) -> None:
    """The supported selfhost case: reachable from another machine, and guarded."""
    result = _run_entrypoint(tmp_path, bind=_EXPOSED_ADDRESS, password=_PASSWORD)

    assert result.returncode == 0, result.stderr
    assert _AUTH_ON in _listener_auth(tmp_path, "80")


@pytest.mark.unit
def test_an_exposed_port_80_gets_the_brute_force_backstop(tmp_path: Path) -> None:
    """Port 80's exemption from the auth rate limit was justified by "loopback only"."""
    _run_entrypoint(tmp_path, bind=_EXPOSED_ADDRESS, password=_PASSWORD)

    assert "limit_req zone=auth" in _listener_auth(tmp_path, "80")


@pytest.mark.unit
def test_the_default_bind_keeps_port_80_unauthenticated(tmp_path: Path) -> None:
    """Local dev, testing and Playwright must be untouched by all of this."""
    result = _run_entrypoint(tmp_path, bind=None, password="")

    assert result.returncode == 0, result.stderr
    assert _listener_auth(tmp_path, "80").strip() == _AUTH_OFF


@pytest.mark.unit
def test_a_password_alone_does_not_authenticate_the_loopback_port(tmp_path: Path) -> None:
    """Setting a password for the tunnel must not start prompting on localhost.

    This is the behaviour-preservation half of the rule: auth on port 80 follows
    reachability, not the mere presence of a password.
    """
    _run_entrypoint(tmp_path, bind="127.0.0.1", password=_PASSWORD)

    assert _listener_auth(tmp_path, "80").strip() == _AUTH_OFF


@pytest.mark.unit
def test_the_tunnel_port_auth_still_follows_the_password_alone(tmp_path: Path) -> None:
    """Port 8081 is reached by cloudflared however the host binds; unchanged."""
    _run_entrypoint(tmp_path, bind="127.0.0.1", password=_PASSWORD)

    assert _AUTH_ON in _listener_auth(tmp_path, "8081")


@pytest.mark.unit
@pytest.mark.parametrize("address", ["127.0.0.1", "127.0.0.53", "::1", "[::1]", "localhost", ""])
def test_loopback_addresses_need_no_password(tmp_path: Path, address: str) -> None:
    """``::1`` is loopback. The field description used to say otherwise.

    The empty string is here rather than below because both the ``ports:`` entry
    and the entrypoint read it through ``${SYN_GATEWAY_BIND:-127.0.0.1}``, which
    resolves empty to the default. Docker binds loopback in that case, so
    treating it as exposed would refuse to start a stack that is not exposed.
    """
    result = _run_entrypoint(tmp_path, bind=address, password="")

    assert result.returncode == 0, f"{address} was treated as exposed:\n{result.stderr}"


@pytest.mark.unit
@pytest.mark.parametrize("address", ["0.0.0.0", "10.0.0.4", "127.foo.example", "::"])
def test_non_loopback_addresses_need_a_password(tmp_path: Path, address: str) -> None:
    """``127.foo.example`` is a hostname that merely starts with 127.

    Every one of these must fail closed: guessing wrong in this direction
    publishes the API to the network.
    """
    result = _run_entrypoint(tmp_path, bind=address, password="")

    assert result.returncode != 0, f"{address!r} was treated as loopback"


# ---------------------------------------------------------------------------
# The hops after the decision
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_port_80_block_includes_whatever_file_the_bind_decision_writes(
    tmp_path: Path,
) -> None:
    """Guards the drop between the entrypoint and nginx.

    A stanza written to a file no server block includes changes nothing, and
    every test either side of that gap still passes. So: find the snippets whose
    content actually reacts to ``SYN_GATEWAY_BIND``, and require the listener
    that ``SYN_GATEWAY_BIND`` publishes to include them.
    """
    _run_entrypoint(tmp_path / "loopback", bind="127.0.0.1", password=_PASSWORD)
    _run_entrypoint(tmp_path / "exposed", bind=_EXPOSED_ADDRESS, password=_PASSWORD)

    loopback = _generated(tmp_path / "loopback")
    exposed = _generated(tmp_path / "exposed")
    reacts = {name for name, body in loopback.items() if exposed.get(name) != body}

    assert reacts, "no generated nginx snippet responds to SYN_GATEWAY_BIND at all"

    port_80_includes = _includes(_server_block(_NGINX_CONF.read_text(), "80"))
    for name in reacts:
        assert f"{_default_auth_dir()}/{name}" in port_80_includes, (
            f"{name} encodes the bind decision but the port 80 server block does "
            f"not include it, so the decision has no effect"
        )


# ---------------------------------------------------------------------------
# The hop before the decision: compose has to hand the bind to the container
# ---------------------------------------------------------------------------

#: Every compose file in the repo, discovered rather than listed. The listed
#: version of this held selfhost and the file generated from it, and the
#: on-demand stack published port 80 through a variable of its own for months
#: without ever being added to it (#1148). An allowlist of files to check is a
#: list someone has to remember to extend, and the one that got forgotten is
#: exactly the one that was exposed - so the question asked below is "which
#: files publish port 80", not "which files did we think of".
_COMPOSE_DIR = _REPO_ROOT / "docker"


def _compose_files() -> list[Path]:
    files = sorted(_COMPOSE_DIR.glob("*.yaml"))
    assert files, f"no compose files found under {_COMPOSE_DIR}"
    return files


def _split_port_spec(spec: str) -> list[str]:
    """Split ``host_ip:published:target`` on colons outside ``${...}``.

    ``${SYN_GATEWAY_PORT:-8137}`` contains a colon of its own, so splitting the
    raw string gets the fields wrong -- quietly, and in a way that still yields
    three of them.

    A two-field publish (``"9137:80"``) names no interface and so binds every
    one of them -- that is the original #1148 defect, and it is reported as an
    empty host_ip rather than raised. Raising here would abort collection and
    take all of this file's tests with it, turning the clearest possible
    finding into an error message about a list length.
    """
    fields: list[str] = [""]
    depth = 0
    for index, char in enumerate(spec):
        if char == "{" and index and spec[index - 1] == "$":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        if char == ":" and not depth:
            fields.append("")
            continue
        fields[-1] += char
    assert len(fields) <= 3, f"expected host_ip:published:target, got {fields!r} from {spec!r}"
    return ["", *fields][-3:]


def _environment(service: dict[str, object]) -> dict[str, str]:
    """Compose accepts list and mapping form; the files differ."""
    declared = service.get("environment", {})
    if isinstance(declared, list):
        pairs = [str(item).split("=", 1) for item in declared]
        return {key: value for key, *rest in pairs for value in (rest[0] if rest else "",)}
    assert isinstance(declared, dict)
    return {str(k): str(v) for k, v in declared.items()}


@dataclass(frozen=True)
class Port80Publish:
    """A service that publishes container port 80 to the host, and its env.

    No gateway service is defined across two compose files -- each of the four
    declares its own ``ports`` and ``environment`` together -- so reading one
    file is reading the whole service. ``test_no_service_splits_port_80_across_files``
    keeps that true.
    """

    compose_file: Path
    service: str
    host_ip_expression: str
    environment: dict[str, str]

    def __str__(self) -> str:
        return f"{self.compose_file.name}:{self.service}"


def _port_80_publishes() -> list[Port80Publish]:
    """Every host publish of container port 80, across every compose file.

    Port 80 rather than the service name ``gateway``: what the entrypoint's
    rule is about is the host-published HTTP listener, and a second one added
    under another name would need the same wiring, not an exemption.
    """
    found: list[Port80Publish] = []
    for compose_file in _compose_files():
        document = yaml.safe_load(compose_file.read_text()) or {}
        for name, service in (document.get("services") or {}).items():
            if not isinstance(service, dict):
                continue
            for entry in service.get("ports") or []:
                fields = _split_port_spec(str(entry))
                if fields[-1] != "80":
                    continue
                found.append(
                    Port80Publish(
                        compose_file=compose_file,
                        service=str(name),
                        host_ip_expression=fields[0],
                        environment=_environment(service),
                    )
                )
    assert found, "no compose file publishes container port 80 -- discovery is broken"
    return found


_PORT_80 = _port_80_publishes()


@pytest.mark.unit
def test_discovery_sees_every_stack_that_publishes_the_gateway() -> None:
    """Discovery failing open is the one outcome this design cannot afford.

    If the glob, the parse or the port match silently stops finding files, the
    two tests below iterate an empty list and report success. Naming the stacks
    that exist today makes that show up as a failure rather than as a green run
    over nothing.
    """
    assert {publish.compose_file.name for publish in _PORT_80} == {
        "docker-compose.dev.yaml",
        "docker-compose.ondemand.yaml",
        "docker-compose.selfhost.yaml",
        "docker-compose.syntropic137.yaml",
    }


@pytest.mark.unit
def test_no_service_splits_port_80_across_files() -> None:
    """Reading one file has to be reading the whole service.

    Every check here pairs a ``ports`` entry with the ``environment`` beside
    it. If an overlay ever published port 80 while the bind arrived from the
    base file, that pairing would be reading half a service and would fail a
    correctly-wired stack -- so require the two to stay together.
    """
    for publish in _PORT_80:
        document = yaml.safe_load(publish.compose_file.read_text())
        service = document["services"][publish.service]
        assert "environment" in service, (
            f"{publish} publishes port 80 but declares no environment of its own; "
            f"the bind can no longer be read from the same file as the port"
        )


@pytest.mark.unit
@pytest.mark.parametrize("publish", _PORT_80, ids=str)
def test_the_gateway_is_told_the_address_it_is_published_on(publish: Port80Publish) -> None:
    """A published port 80 is either pinned to loopback or hands over its bind.

    If the ``ports`` expression and ``SYN_GATEWAY_BIND`` drift -- or if a stack
    publishes port 80 through a variable and simply omits the variable, which
    is how the on-demand stack stayed exposed -- the entrypoint sees the
    loopback default, decides "not exposed", and serves an unauthenticated API
    on whatever address docker actually bound.
    """
    if not variable_names(publish.host_ip_expression):
        assert publish.host_ip_expression, (
            f"{publish} publishes port 80 with no host interface at all, which "
            f"binds every one of them"
        )
        assert binds_loopback(publish.host_ip_expression), (
            f"{publish} hard-wires the non-loopback address "
            f"{publish.host_ip_expression!r}, which nothing can opt out of"
        )
        return

    assert publish.environment.get("SYN_GATEWAY_BIND") == publish.host_ip_expression, (
        f"{publish} publishes port 80 on {publish.host_ip_expression!r} but does not pass "
        f"that same expression to the container as SYN_GATEWAY_BIND"
    )


# ---------------------------------------------------------------------------
# End to end: the unsafe combination, built the way an operator builds it
# ---------------------------------------------------------------------------


def _container_environment(publish: Port80Publish, shell: dict[str, str]) -> dict[str, str]:
    """What the container receives when the operator's shell holds `shell`.

    Uses the repo's own Compose interpolation (`scripts/no_public_ports`, which
    has its own fixtures) rather than a second resolver written here: a private
    copy could be wrong in the same direction as the code it is checking, and
    then both would agree that an exposed stack is fine.
    """
    return {key: interpolate(value, shell) for key, value in publish.environment.items()}


#: The publishes an operator can actually widen. The pinned-loopback ones are
#: not skipped for convenience -- there is no shell variable that moves them,
#: so there is no unsafe combination to construct.
_WIDENABLE = [publish for publish in _PORT_80 if variable_names(publish.host_ip_expression)]


@pytest.mark.unit
def test_at_least_one_stack_is_widenable() -> None:
    """Otherwise the two tests below silently assert nothing at all."""
    assert _WIDENABLE


@pytest.mark.unit
@pytest.mark.parametrize("publish", _WIDENABLE, ids=str)
def test_widening_the_bind_with_no_password_refuses_to_start(publish: Port80Publish) -> None:
    """The invariant, exercised end to end on every path that can widen a bind.

    Not "does the compose file look right" and not "does the entrypoint refuse
    when handed a bind" -- both of those passed while the on-demand stack was
    exposed. This sets the variable an operator sets, resolves the compose file
    the way docker resolves it, and hands the result to the real entrypoint.
    """
    shell = dict.fromkeys(variable_names(publish.host_ip_expression), _EXPOSED_ADDRESS)

    assert interpolate(publish.host_ip_expression, shell) == _EXPOSED_ADDRESS, (
        f"{publish}: setting {sorted(shell)} did not move the published address, so "
        f"this test is not building the unsafe combination it claims to"
    )

    with tempfile.TemporaryDirectory() as workdir:
        result = _run_entrypoint_with(Path(workdir), _container_environment(publish, shell))

    assert result.returncode != 0, (
        f"{publish} published port 80 on {_EXPOSED_ADDRESS} and the gateway started "
        f"anyway, unauthenticated:\n{result.stdout}"
    )
    assert _EXPOSED_ADDRESS in result.stderr, "the error must name the bind that caused it"
    assert "SYN_API_PASSWORD" in result.stderr, "the error must name the way out"


@pytest.mark.unit
@pytest.mark.parametrize("publish", _WIDENABLE, ids=str)
def test_widening_the_bind_with_a_password_is_supported_and_authenticated(
    publish: Port80Publish,
) -> None:
    """The other half of the coupling, without which "refuse" is satisfiable by
    a stack that never starts.

    Every widenable path must have a way through: set the password the error
    message names, and the port comes up behind Basic Auth. The on-demand stack
    hard-wired ``SYN_API_PASSWORD=`` and so had no way through at all.
    """
    shell = dict.fromkeys(variable_names(publish.host_ip_expression), _EXPOSED_ADDRESS)
    shell["SYN_API_PASSWORD"] = _PASSWORD

    with tempfile.TemporaryDirectory() as workdir:
        path = Path(workdir)
        result = _run_entrypoint_with(path, _container_environment(publish, shell))

        assert result.returncode == 0, (
            f"{publish} has no supported off-loopback configuration: setting "
            f"SYN_API_PASSWORD did not let it start.\n{result.stderr}"
        )
        assert _AUTH_ON in _listener_auth(path, "80")
