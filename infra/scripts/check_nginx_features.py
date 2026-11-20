"""Refuse nginx config that enables HTTP/2, HTTP/3, TLS, resolver, mail or stream.

The gateway and dashboard images serve plain HTTP/1.1. nginx's security
advisories keep landing in exactly the modules this script refuses (the
2026-11-18 release, CVE-2026-123007 and nine more, was HTTP/2, HTTP/3, TLS,
resolver, mail, stream and PROXY protocol), so a config that turns one on makes
the next advisory reachable whatever version is pinned (#2335).

It parses directives rather than grepping text: comments end at a newline only
when the ``#`` is outside a quoted string, and ``;``, ``{`` and ``}`` separate
directives wherever they fall, so neither ``add_header X "#"; http2 on;`` nor
``events {} stream {`` can hide a directive.

Two consumers:

- the unit test runs it on every nginx config file in the repository;
- ``just skyline-gateway-smoke`` (and CI's gateway job) pipes ``nginx -T`` from
  the running gateway into it, which is the rendered config: the base image's
  ``nginx.conf``, every include and the stanzas the entrypoint generates.

Usage: ``check_nginx_features.py FILE...`` or ``nginx -T | check_nginx_features.py -``.
Exit 0 when nothing is enabled, 1 with one line per finding otherwise.
Standard library only, so it runs under a bare ``python3`` in CI.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Directive:
    name: str
    args: tuple[str, ...]
    line: int
    opens_block: bool


def parse(text: str) -> list[Directive]:
    """Every directive in ``text``, in order, with its arguments unquoted."""
    directives: list[Directive] = []
    words: list[str] = []
    word: list[str] = []
    word_started = False
    start_line = 0
    line = 1
    i = 0
    n = len(text)

    def end_word() -> None:
        nonlocal word, word_started
        if word_started:
            words.append("".join(word))
        word = []
        word_started = False

    def end_directive(opens_block: bool) -> None:
        nonlocal words
        end_word()
        if words:
            directives.append(Directive(words[0], tuple(words[1:]), start_line, opens_block))
        words = []

    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        if c in "\"'":
            if not words and not word_started:
                start_line = line
            word_started = True
            quote = c
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    i += 1
                if text[i] == "\n":
                    line += 1
                word.append(text[i])
                i += 1
            i += 1
            continue
        if c == "#" and not word_started:
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c.isspace():
            end_word()
        elif c == ";":
            end_directive(opens_block=False)
        elif c == "{":
            end_directive(opens_block=True)
        elif c == "}":
            end_directive(opens_block=False)
        else:
            if not words and not word_started:
                start_line = line
            if c == "\\" and i + 1 < n:
                i += 1
                c = text[i]
            word_started = True
            word.append(c)
        i += 1
    end_directive(opens_block=False)
    return directives


#: ``listen`` parameters that enable an affected module.
_LISTEN_FLAGS = frozenset({"http2", "quic", "ssl", "proxy_protocol"})
#: Switch directives that are fine only when set to ``off``.
_SWITCHES = frozenset({"http2", "http3", "http3_hq", "ssl", "proxy_protocol"})
#: Blocks that load a whole affected module.
_BLOCKS = frozenset({"mail", "stream"})


def findings(directives: list[Directive]) -> list[str]:
    """One message per directive that enables an affected feature."""
    found: list[str] = []
    for d in directives:
        args = [a.lower() for a in d.args]
        name = d.name.lower()
        if name == "listen":
            flags = sorted(_LISTEN_FLAGS.intersection(args))
            if flags:
                found.append(f"line {d.line}: listen {' '.join(d.args)} enables {', '.join(flags)}")
        elif name in _SWITCHES:
            if args != ["off"]:
                found.append(f"line {d.line}: {d.name} {' '.join(d.args)}")
        elif name in _BLOCKS and d.opens_block:
            found.append(f"line {d.line}: {d.name} {{ }} block")
        elif name.startswith(("ssl_", "quic_", "http3_")) or name == "resolver":
            found.append(f"line {d.line}: {d.name}")
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_nginx_features.py FILE... | -", file=sys.stderr)
        return 2
    bad = 0
    for arg in argv:
        text = sys.stdin.read() if arg == "-" else Path(arg).read_text()
        label = "stdin" if arg == "-" else arg
        for message in findings(parse(text)):
            print(f"{label}: {message}")
            bad += 1
    if bad:
        print(f"{bad} disallowed nginx feature(s): the gateway serves plain HTTP/1.1 only (#2335)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
