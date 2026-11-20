"""Refuse nginx config that enables HTTP/2, HTTP/3, TLS, resolver, mail or stream.

The gateway and dashboard images serve plain HTTP/1.1. nginx's security
advisories keep landing in exactly the modules this script refuses (the
2026-11-18 release, led by CVE-2026-123007, was HTTP/2, HTTP/3, TLS, resolver,
mail, stream and PROXY protocol), so a config that turns one on makes the next
advisory reachable whatever version is pinned (#2335).

It reads directives the way nginx does, not by grepping text. ``parse`` is a
port of nginx's own tokenizer (``ngx_conf_read_token`` in
``src/core/ngx_conf_file.c``, 1.30.7): only space, tab, CR and LF are
whitespace; ``;`` and ``{`` end a word, ``}`` does not; a quote opens a string
and ``#`` opens a comment only at the start of a token; a backslash escapes the
next character. Anything nginx would refuse to load is reported as a finding
rather than guessed at, so a config this script cannot read never passes.

Two consumers:

- the unit test runs it on every nginx config file in the repository;
- ``just skyline-gateway-smoke`` (and CI's gateway job) runs it on ``nginx -T``
  from the running gateway, which is the rendered config: the base image's
  ``nginx.conf``, every include and the stanzas the entrypoint generates.

Usage: ``check_nginx_features.py FILE...`` or ``nginx -T | check_nginx_features.py -``.
Exit 0 when nothing is enabled, 1 with one line per finding otherwise.
Standard library only, so it runs under a bare ``python3`` in CI.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

#: nginx's whitespace: exactly these four (not form feed, not vertical tab).
_WS = frozenset(" \t\r\n")

#: Escapes nginx resolves inside a token (ngx_conf_read_token, `found` branch).
_UNESCAPE = {'"': '"', "'": "'", "\\": "\\", "t": "\t", "r": "\r", "n": "\n"}


class NginxSyntaxError(ValueError):
    """Config nginx itself would refuse to load."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


@dataclass(frozen=True)
class Directive:
    name: str
    args: tuple[str, ...]
    line: int
    opens_block: bool


def _unescape(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw) and raw[i + 1] in _UNESCAPE:
            out.append(_UNESCAPE[raw[i + 1]])
            i += 2
            continue
        out.append(raw[i])
        i += 1
    return "".join(out)


class _Tokenizer:
    """``ngx_conf_read_token`` as a state machine, one method per state."""

    def __init__(self) -> None:
        self.directives: list[Directive] = []
        self.args: list[str] = []
        self.word: list[str] = []
        self.line = 1
        self.start_line = 1
        self.depth = 0
        self.last_space = True
        self.need_space = False
        self.sharp_comment = False
        self.escaped = False
        self.variable = False
        self.quote = ""

    def _end_word(self) -> None:
        self.args.append(_unescape("".join(self.word)))
        self.word.clear()

    def _end_directive(self, *, opens_block: bool) -> None:
        if not self.args:
            raise NginxSyntaxError(self.line, f'unexpected "{"{" if opens_block else ";"}"')
        self.directives.append(
            Directive(self.args[0], tuple(self.args[1:]), self.start_line, opens_block)
        )
        self.args.clear()
        self.last_space = True
        if opens_block:
            self.depth += 1

    def feed(self, ch: str) -> None:
        if ch == "\n":
            self.line += 1
            self.sharp_comment = False
        elif ch not in _WS and (ord(ch) < 0x20 or ord(ch) == 0x7F):
            # nginx keeps control bytes inside a word, and its handlers compare
            # C strings, so "proxy_protocol\0x" reads as proxy_protocol there
            # (Codex review, pass 4). No legitimate config carries one: refuse.
            raise NginxSyntaxError(self.line, f"control character 0x{ord(ch):02x}")
        if self.sharp_comment:
            return
        if self.escaped:
            self.escaped = False
            self.word.append(ch)
        elif self.need_space:
            self._after_quote(ch)
        elif self.last_space:
            self._at_token_start(ch)
        else:
            self._in_token(ch)

    def _after_quote(self, ch: str) -> None:
        """A quoted token just closed: nginx demands a separator next."""
        self.need_space = False
        if ch in _WS:
            self.last_space = True
        elif ch == ")":
            # nginx accepts `)` here and keeps it as the next token's first byte.
            self.last_space = True
            self._at_token_start(ch)
        elif ch in ";{":
            self._end_directive(opens_block=ch == "{")
        else:
            raise NginxSyntaxError(self.line, f'unexpected "{ch}"')

    def _at_token_start(self, ch: str) -> None:
        if ch in _WS:
            return
        if not self.args:
            self.start_line = self.line
        if ch in ";{":
            self._end_directive(opens_block=ch == "{")
        elif ch == "}":
            if self.args or self.depth == 0:
                raise NginxSyntaxError(self.line, 'unexpected "}"')
            self.depth -= 1
        elif ch == "#":
            self.sharp_comment = True
        else:
            self.last_space = False
            if ch in "\"'":
                self.quote = ch
            else:
                self._literal(ch)

    def _literal(self, ch: str) -> None:
        """A character that is part of the word, and may start an escape or variable."""
        self.word.append(ch)
        if ch == "\\":
            self.escaped = True
        elif ch == "$":
            self.variable = True

    def _in_token(self, ch: str) -> None:
        if ch == "{" and self.variable:
            self.word.append(ch)
            return
        self.variable = False
        if ch in "\\$":
            self._literal(ch)
        elif self.quote:
            if ch == self.quote:
                self.quote = ""
                self._end_word()
                self.need_space = True
            else:
                self.word.append(ch)
        elif ch in _WS or ch in ";{":
            self._end_word()
            self.last_space = True
            if ch in ";{":
                self._end_directive(opens_block=ch == "{")
        else:
            self.word.append(ch)

    def finish(self) -> list[Directive]:
        if self.quote or not self.last_space or self.args or self.need_space or self.escaped:
            raise NginxSyntaxError(self.line, 'unexpected end of file, expecting ";" or "}"')
        if self.depth:
            raise NginxSyntaxError(self.line, 'unexpected end of file, expecting "}"')
        return self.directives


def parse(text: str) -> list[Directive]:
    """Every directive in ``text``, in order, as nginx tokenizes it.

    Raises ``NginxSyntaxError`` where nginx would report "unexpected" or
    "unbalanced" and refuse the file.
    """
    tokenizer = _Tokenizer()
    for ch in text:
        tokenizer.feed(ch)
    return tokenizer.finish()


#: ``listen`` parameters that enable an affected module.
_LISTEN_FLAGS = frozenset({"http2", "quic", "ssl", "proxy_protocol"})
#: Switch directives that are fine only when set to ``off``.
_SWITCHES = frozenset({"http2", "http3", "http3_hq", "ssl", "proxy_protocol"})
#: Blocks that load a whole affected module.
_BLOCKS = frozenset({"mail", "stream"})


def findings(directives: list[Directive]) -> list[str]:
    """One message per directive that enables an affected feature.

    Names are matched case-insensitively. nginx's are case-sensitive, so this
    is stricter than nginx, never looser.
    """
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


def check(text: str) -> list[str]:
    """Findings for ``text``; a config nginx would refuse is itself a finding."""
    try:
        return findings(parse(text))
    except NginxSyntaxError as err:
        return [f"{err} (nginx would refuse this config; not checked further)"]


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_nginx_features.py FILE... | -", file=sys.stderr)
        return 2
    bad = 0
    for arg in argv:
        text = sys.stdin.read() if arg == "-" else Path(arg).read_text()
        label = "stdin" if arg == "-" else arg
        for message in check(text):
            print(f"{label}: {message}")
            bad += 1
    if bad:
        print(f"{bad} disallowed nginx feature(s): the gateway serves plain HTTP/1.1 only (#2335)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
