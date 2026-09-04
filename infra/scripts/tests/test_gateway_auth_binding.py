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
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

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


def _run_entrypoint(
    workdir: Path, *, bind: str | None, password: str
) -> subprocess.CompletedProcess[str]:
    """Run the gateway entrypoint with a stub ``htpasswd`` and its own AUTH_DIR.

    ``htpasswd`` ships in the image (apache2-utils) but not on a dev machine or
    in CI, and what it writes is irrelevant here -- only whether nginx is told
    to consult it. Stubbing it keeps these tests dependency-free rather than
    skipping, and a check that skips is a check that cannot fail.
    """
    bin_dir = workdir / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "htpasswd"
    stub.write_text('#!/bin/sh\nprintf "stub\\n" > "$2"\n')
    stub.chmod(0o755)

    auth_dir = workdir / "auth"
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "AUTH_DIR": str(auth_dir),
        "SYN_API_PASSWORD": password,
    }
    if bind is not None:
        env["SYN_GATEWAY_BIND"] = bind

    return subprocess.run(
        ["sh", str(_ENTRYPOINT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


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

#: The selfhost source overlay and the published file generated from it. Both,
#: because reverting only the source leaves the published artifact correct until
#: the next regeneration -- a mutation that survived the original PR's tests.
_COMPOSE_FILES = (
    _REPO_ROOT / "docker" / "docker-compose.selfhost.yaml",
    _REPO_ROOT / "docker" / "docker-compose.syntropic137.yaml",
)


def _split_port_spec(spec: str) -> list[str]:
    """Split ``host_ip:published:target`` on colons outside ``${...}``.

    ``${SYN_GATEWAY_PORT:-8137}`` contains a colon of its own, so splitting the
    raw string gets the fields wrong -- quietly, and in a way that still yields
    three of them.
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
    assert len(fields) == 3, f"expected host_ip:published:target, got {fields!r} from {spec!r}"
    return fields


def _gateway_service(path: Path) -> dict[str, object]:
    service = yaml.safe_load(path.read_text())["services"]["gateway"]
    assert isinstance(service, dict)
    return service


def _environment(service: dict[str, object]) -> dict[str, str]:
    """Compose accepts list and mapping form; the two files differ."""
    declared = service.get("environment", {})
    if isinstance(declared, list):
        pairs = [str(item).split("=", 1) for item in declared]
        return {key: value for key, *rest in pairs for value in (rest[0] if rest else "",)}
    assert isinstance(declared, dict)
    return {str(k): str(v) for k, v in declared.items()}


@pytest.mark.unit
@pytest.mark.parametrize("compose_file", _COMPOSE_FILES, ids=lambda p: p.name)
def test_the_gateway_is_told_the_address_it_is_published_on(compose_file: Path) -> None:
    """The host_ip expression and SYN_GATEWAY_BIND must be the same expression.

    If they drift -- or if a stack publishes port 80 and simply omits the
    variable -- the entrypoint sees the loopback default, decides "not exposed",
    and serves an unauthenticated API on whatever address docker actually bound.
    The check above it cannot notice; only this one can.
    """
    service = _gateway_service(compose_file)
    ports = service.get("ports")
    assert isinstance(ports, list)

    published_80 = [
        fields for fields in (_split_port_spec(str(entry)) for entry in ports) if fields[-1] == "80"
    ]
    assert len(published_80) == 1, f"expected one gateway port 80 mapping, got {ports}"

    host_ip, _published_port, _target = published_80[0]
    assert _environment(service).get("SYN_GATEWAY_BIND") == host_ip, (
        f"{compose_file.name} publishes port 80 on {host_ip!r} but does not pass that "
        f"same expression to the container as SYN_GATEWAY_BIND"
    )
