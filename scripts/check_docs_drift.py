"""Find commands and API paths in the docs that the shipped software rejects.

A docs page that tells a reader to run a subcommand that does not exist, pass
a flag the parser refuses, or call an endpoint the API does not serve is a
false claim, and nothing else in the build notices it (#1946: every command in
"Run Your First Workflow" was wrong on v1.0.0). This measures three things,
each against the artifact the software is built from, never against prose:

- ``syn ...`` commands, against ``apps/syn-cli-node/cli-manifest.json``, which
  ``just codegen`` writes from the same registry the CLI dispatches from.
- ``/api/v1/...`` paths (and their method, when one is written), against the
  generated OpenAPI spec ``apps/syn-docs/openapi.json``.
- ``npx @syntropic137/setup ...`` commands, against
  ``ci/fitness/docs_drift/setup-cli-manifest.json``, vendored from the setup
  repo because it exports no manifest of its own (see that file's ``source``).

Commands are read from fenced code blocks and from inline code spans. A
command that is illustrative on purpose (a placeholder subcommand, a path that
only exists behind the gateway) is allowed only by an entry in the
``[docs_drift]`` table of ``ci/fitness/fitness_exceptions.toml`` that quotes it
exactly and says why. Nothing is skipped silently: an allow entry that matches
nothing is itself a finding, so a fixed page cannot leave its waiver behind.

The fitness test ``ci/fitness/code_quality/test_docs_drift.py`` holds the
budget. Run this directly to see every finding:

    uv run python scripts/check_docs_drift.py
"""

from __future__ import annotations

import json
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
CLI_MANIFEST: Final = REPO_ROOT / "apps" / "syn-cli-node" / "cli-manifest.json"
OPENAPI_SPEC: Final = REPO_ROOT / "apps" / "syn-docs" / "openapi.json"
SETUP_MANIFEST: Final = REPO_ROOT / "ci" / "fitness" / "docs_drift" / "setup-cli-manifest.json"
EXCEPTIONS: Final = REPO_ROOT / "ci" / "fitness" / "fitness_exceptions.toml"

DOC_GLOBS: Final = ("apps/syn-docs/content/**/*.mdx", "README.md")

API_PREFIX: Final = "/api/v1"
HTTP_METHODS: Final = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
SETUP_PACKAGE: Final = "@syntropic137/setup"
CLI_PACKAGE: Final = "@syntropic137/cli"

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_SHELL_SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\||\$\(|`)\s*")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
_PROMPT = re.compile(r"^\s*(?:\$|>|#)\s+")
_PATH_CHARS = r"[^\s`'\")\]\[,;|]"
_API_PATH = re.compile(
    r"(?:\b(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?:https?://[^\s/`'\"]+)?)?"
    rf"(?P<path>/api/v1(?:/{_PATH_CHARS}*)?)"
)
# `GET /executions/{id}`: a method and a path with the prefix left off, the way
# the guides name routes. Only read inside code, where it is unambiguous.
_BARE_ROUTE = re.compile(
    rf"(?<![\w/])(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>/(?!api/v1\b){_PATH_CHARS}*)"
)
# `API="$SYN_API_URL/api/v1"` then `$API/executions/...` in the same block.
_API_VAR_ASSIGN = re.compile(r"\b(?P<var>[A-Za-z_]\w*)=[\"']?\S*/api/v1/?[\"']?(?:\s|$)")
_CURL_METHOD = re.compile(r"(?:-X|--request)\s+['\"]?(GET|POST|PUT|PATCH|DELETE)\b")
# A path segment a reader is meant to substitute: {id}, <id>, :id, $ID, ${ID}, ...
_PLACEHOLDER_SEGMENT = re.compile(r"^(?:\{[^}]*\}|<[^>]*>|:\w+|\$\{?\w+\}?|\.\.\.|\[[^\]]*\])$")
_SHORT_SLASH_LONG = re.compile(r"^-\w/--[\w-]+$")
_PLACEHOLDER_TOKEN = re.compile(r"^(?:<[^>]*>|\[[^\]]*\]|\{[^}]*\}|\.\.\.|\$\{?\w+\}?)$")


class Kind(StrEnum):
    SYN = "syn"
    API = "api"
    SETUP = "setup"


@dataclass(frozen=True)
class Snippet:
    """One command or path as it appears on a page."""

    file: str
    line: int
    kind: Kind
    text: str
    method: str | None = None
    # API snippets only: the path below /api/v1 that the text names.
    route: str = ""


@dataclass(frozen=True)
class Finding:
    snippet: Snippet
    problem: str

    def render(self) -> str:
        s = self.snippet
        return f"{s.file}:{s.line}: [{s.kind}] {s.text!r}: {self.problem}"


# ── Manifests ───────────────────────────────────────────────────────────────


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Option(_Frozen):
    name: str
    short: str | None
    takes_value: bool


class Command(_Frozen):
    """One `syn` command; the JSON shape written by generate-cli-manifest.ts."""

    name: str
    args: tuple[str, ...]
    options: tuple[Option, ...]

    def find(self, flag: str, global_options: Sequence[Option]) -> Option | None:
        for opt in (*self.options, *global_options):
            if flag == f"--{opt.name}" or (opt.short is not None and flag == f"-{opt.short}"):
                return opt
        return None


class Group(_Frozen):
    name: str
    commands: tuple[Command, ...]

    def get(self, name: str) -> Command | None:
        return next((c for c in self.commands if c.name == name), None)


class CliManifest(_Frozen):
    global_options: tuple[Option, ...]
    top_level_flags: frozenset[str]
    root_commands: tuple[Command, ...]
    groups: tuple[Group, ...]

    @classmethod
    def load(cls, path: Path = CLI_MANIFEST) -> CliManifest:
        return cls.model_validate_json(path.read_text())

    def root(self, name: str) -> Command | None:
        return next((c for c in self.root_commands if c.name == name), None)

    def group(self, name: str) -> Group | None:
        return next((g for g in self.groups if g.name == name), None)


class SetupCommand(_Frozen):
    name: str
    flags: frozenset[str]
    actions: frozenset[str] = frozenset()


class SetupSource(_Frozen):
    repo: str
    commit: str
    version: str
    tracking: str
    files: tuple[str, ...]
    why_vendored: str


class SetupManifest(_Frozen):
    source: SetupSource
    global_flags: frozenset[str]
    menu_flags: frozenset[str]
    value_flags: frozenset[str]
    commands: tuple[SetupCommand, ...]

    @classmethod
    def load(cls, path: Path = SETUP_MANIFEST) -> SetupManifest:
        return cls.model_validate_json(path.read_text())

    def command(self, name: str) -> SetupCommand | None:
        return next((c for c in self.commands if c.name == name), None)


@dataclass(frozen=True)
class ApiRoute:
    segments: tuple[str, ...]
    methods: frozenset[str]

    def matches(self, doc_segments: Sequence[str]) -> bool:
        if len(doc_segments) != len(self.segments):
            return False
        for doc, spec in zip(doc_segments, self.segments, strict=True):
            templated = spec.startswith("{") and spec.endswith("}")
            if _PLACEHOLDER_SEGMENT.match(doc):
                if not templated:
                    return False
            elif not templated and doc != spec:
                return False
        return True


def load_api_routes(path: Path = OPENAPI_SPEC) -> list[ApiRoute]:
    raw = json.loads(path.read_text())
    return [
        ApiRoute(
            tuple(s for s in route.split("/") if s),
            frozenset(m.upper() for m in ops if m.upper() in HTTP_METHODS),
        )
        for route, ops in raw["paths"].items()
    ]


# ── Extraction ──────────────────────────────────────────────────────────────


def _logical_code_lines(lines: Sequence[str]) -> Iterator[tuple[int, str]]:
    """Code-block lines, with backslash continuations joined. 1-based."""
    buf: list[str] = []
    start = 0
    for i, line in enumerate(lines, 1):
        if not buf:
            start = i
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buf.append(stripped[:-1])
            continue
        buf.append(stripped)
        yield start, " ".join(part.strip() for part in buf)
        buf = []
    if buf:
        yield start, " ".join(part.strip() for part in buf)


def _strip_comment(line: str) -> str:
    # A ` #` outside quotes starts a shell comment.
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def _command_segments(line: str) -> Iterator[str]:
    line = _PROMPT.sub("", line, count=1)
    for seg in _SHELL_SEPARATORS.split(_strip_comment(line)):
        seg = seg.strip().rstrip(")")
        if seg:
            yield seg


def _tokens(segment: str) -> list[str]:
    try:
        toks = shlex.split(segment, comments=False, posix=True)
    except ValueError:
        toks = segment.split()
    while toks and (_ENV_ASSIGNMENT.match(toks[0]) or toks[0] in {"sudo", "exec", "time"}):
        toks = toks[1:]
    return toks


def classify(segment: str) -> tuple[Kind, list[str]] | None:
    """Return the command kind and its arguments, or None for anything else."""
    toks = _tokens(segment)
    if not toks:
        return None
    if toks[0] == "syn":
        return Kind.SYN, toks[1:]
    if toks[0] in {"npx", "pnpx"} or toks[:2] == ["pnpm", "dlx"]:
        rest = toks[2:] if toks[0] == "pnpm" else toks[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        if not rest:
            return None
        pkg = rest[0].rsplit("@", 1)[0] if rest[0].count("@") > 1 else rest[0]
        if pkg == SETUP_PACKAGE:
            return Kind.SETUP, rest[1:]
        if pkg == CLI_PACKAGE:
            return Kind.SYN, rest[1:]
    return None


def _clean_path(path: str) -> str:
    return path.split("?", 1)[0].split("#", 1)[0].rstrip(".:'\"")


def _api_snippets(
    file: str, lineno: int, text: str, *, in_code: bool, api_vars: frozenset[str] = frozenset()
) -> Iterator[Snippet]:
    curl = _CURL_METHOD.search(text)
    curl_method = curl.group(1) if curl else None
    for m in _API_PATH.finditer(text):
        path = _clean_path(m.group("path"))
        if path.rstrip("/") == API_PREFIX:
            continue  # the prefix itself, named in prose
        yield Snippet(
            file, lineno, Kind.API, path, m.group("method") or curl_method, path[len(API_PREFIX) :]
        )
    if not in_code:
        return
    for m in _BARE_ROUTE.finditer(text):
        path = _clean_path(m.group("path"))
        yield Snippet(
            file, lineno, Kind.API, f"{m.group('method')} {path}", m.group("method"), path
        )
    for var in api_vars:
        for m in re.finditer(rf"\$\{{?{var}\}}?(?P<path>/{_PATH_CHARS}*)", text):
            path = _clean_path(m.group("path"))
            yield Snippet(file, lineno, Kind.API, f"${var}{path}", curl_method, path)


def extract(file: str, text: str) -> list[Snippet]:
    """Every syn/setup command and API path on one page."""
    out: list[Snippet] = []
    lines = text.splitlines()
    in_code = False
    code: list[tuple[int, str]] = []

    def flush() -> None:
        api_vars: set[str] = set()
        for start, logical in _logical_code_lines([t for _, t in code]):
            lineno = code[start - 1][0]
            api_vars.update(m.group("var") for m in _API_VAR_ASSIGN.finditer(logical))
            for seg in _command_segments(logical):
                hit = classify(seg)
                if hit:
                    out.append(Snippet(file, lineno, hit[0], seg))
            out.extend(
                _api_snippets(file, lineno, logical, in_code=True, api_vars=frozenset(api_vars))
            )

    for lineno, line in enumerate(lines, 1):
        if _FENCE.match(line):
            if in_code:
                flush()
                code = []
            in_code = not in_code
            continue
        if in_code:
            code.append((lineno, line))
            continue
        for m in _INLINE_CODE.finditer(line):
            span = m.group(1).strip()
            for seg in _command_segments(span):
                hit = classify(seg)
                if hit:
                    out.append(Snippet(file, lineno, hit[0], seg))
            out.extend(_api_snippets(file, lineno, span, in_code=True))
        # Prefixed paths are claims in prose too ("POST /api/v1/foo starts a run").
        prose = _INLINE_CODE.sub(" ", line)
        out.extend(_api_snippets(file, lineno, prose, in_code=False))
    if in_code:
        flush()
    return out


# ── Validation ──────────────────────────────────────────────────────────────


def _check_flags(args: Sequence[str], cmd: Command, cli: CliManifest, label: str) -> str | None:
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            return None
        if tok.startswith("[-"):
            tok = tok[1:].rstrip(".").rstrip("]")  # usage syntax: [--page N]
        if _SHORT_SLASH_LONG.match(tok):
            # Reference syntax: -n/--dry-run names one flag twice.
            short, long_ = tok.split("/", 1)
            for flag in (short, long_):
                if cmd.find(flag, cli.global_options) is None:
                    return f"{label} has no flag {flag}"
            i += 1
            continue
        if tok.startswith("-") and tok != "-" and not _PLACEHOLDER_TOKEN.match(tok):
            flag, has_inline_value = (tok.split("=", 1)[0], True) if "=" in tok else (tok, False)
            if not flag.startswith("--") and len(flag) > 2:
                # Bundled short flags (-nj): each must exist and take no value.
                for ch in flag[1:]:
                    opt = cmd.find(f"-{ch}", cli.global_options)
                    if opt is None:
                        return f"{label} has no flag -{ch}"
                i += 1
                continue
            opt = cmd.find(flag, cli.global_options)
            if opt is None:
                return f"{label} has no flag {flag}"
            if opt.takes_value and not has_inline_value:
                i += 1  # consume the value
            elif not opt.takes_value and has_inline_value:
                return f"{label} flag {flag} takes no value"
        i += 1
    return None


def check_syn(snippet: Snippet, args: Sequence[str], cli: CliManifest) -> str | None:
    if not args or args[0] in cli.top_level_flags:
        return None
    head = args[0]
    if _PLACEHOLDER_TOKEN.match(head):
        return f"placeholder {head} where a command belongs"
    root = cli.root(head)
    if root is not None:
        return _check_flags(args[1:], root, cli, f"syn {head}")
    group = cli.group(head)
    if group is None:
        return f"no command or group named {head!r}"
    if len(args) == 1 or args[1] in {"--help", "-h"}:
        return None
    sub = args[1]
    if _PLACEHOLDER_TOKEN.match(sub):
        return f"placeholder {sub} where a subcommand of syn {head} belongs"
    cmd = group.get(sub)
    if cmd is None:
        names = ", ".join(sorted(c.name for c in group.commands))
        return f"syn {head} has no subcommand {sub!r} (has: {names})"
    return _check_flags(args[2:], cmd, cli, f"syn {head} {sub}")


def check_setup(args: Sequence[str], setup: SetupManifest) -> str | None:
    if not args:
        return None
    command: SetupCommand | None = None
    allowed = setup.menu_flags | setup.global_flags
    value_flags = setup.value_flags
    rest = list(args)
    if not rest[0].startswith("-"):
        name = rest.pop(0)
        command = setup.command(name)
        if command is None:
            names = ", ".join(sorted(c.name for c in setup.commands))
            return f"setup has no command {name!r} (has: {names})"
        allowed = command.flags | setup.global_flags
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("-"):
            flag = tok.split("=", 1)[0]
            if flag not in allowed:
                where = f"setup {command.name}" if command else "setup (no command)"
                return f"{where} does not use flag {flag}"
            if flag in value_flags and "=" not in tok:
                i += 1
        elif command is not None and not _PLACEHOLDER_TOKEN.match(tok):
            if tok not in command.actions:
                return f"setup {command.name} has no action {tok!r}"
        i += 1
    return None


def check_api(snippet: Snippet, routes: Sequence[ApiRoute]) -> str | None:
    segments = [s for s in snippet.route.split("/") if s]
    matching = [r for r in routes if r.matches(segments)]
    if not matching:
        return "no such path in the OpenAPI spec"
    if snippet.method is not None and not any(snippet.method in r.methods for r in matching):
        have = sorted({m for r in matching for m in r.methods})
        return f"{snippet.method} not served (spec has {', '.join(have)})"
    return None


def check(
    snippet: Snippet, cli: CliManifest, setup: SetupManifest, routes: Sequence[ApiRoute]
) -> str | None:
    if snippet.kind is Kind.API:
        return check_api(snippet, routes)
    hit = classify(snippet.text)
    if hit is None:  # pragma: no cover - extract only yields classified text
        return None
    if snippet.kind is Kind.SYN:
        return check_syn(snippet, hit[1], cli)
    return check_setup(hit[1], setup)


# ── Exceptions ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Allow:
    """A reviewed, intentionally illustrative snippet."""

    file: str
    text: str
    reason: str


@dataclass(frozen=True)
class Budget:
    """Grandfathered debt for one file, owned by an open issue."""

    file: str
    max: int
    issue: str


@dataclass(frozen=True)
class Policy:
    allows: tuple[Allow, ...] = ()
    budgets: tuple[Budget, ...] = ()

    @classmethod
    def load(cls, path: Path = EXCEPTIONS) -> Policy:
        with path.open("rb") as f:
            table = tomllib.load(f).get("docs_drift", {})
        return cls(
            allows=tuple(Allow(a["file"], a["text"], a["reason"]) for a in table.get("allow", [])),
            budgets=tuple(
                Budget(file, int(v["max"]), str(v["issue"]))
                for file, v in table.get("budget", {}).items()
            ),
        )


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    allowed: list[Finding] = field(default_factory=list)
    stale_allows: list[Allow] = field(default_factory=list)
    checked: int = 0

    def per_file(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.snippet.file] = counts.get(f.snippet.file, 0) + 1
        return counts


def doc_files(root: Path = REPO_ROOT) -> list[Path]:
    files: set[Path] = set()
    for pattern in DOC_GLOBS:
        files.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(files)


def scan(
    files: Iterable[Path],
    *,
    root: Path = REPO_ROOT,
    cli: CliManifest | None = None,
    setup: SetupManifest | None = None,
    routes: Sequence[ApiRoute] | None = None,
    policy: Policy | None = None,
) -> Report:
    cli = cli or CliManifest.load()
    setup = setup or SetupManifest.load()
    routes = routes if routes is not None else load_api_routes()
    policy = policy or Policy.load()
    report = Report()
    used: set[Allow] = set()
    for path in files:
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
        for snippet in extract(rel, path.read_text()):
            report.checked += 1
            problem = check(snippet, cli, setup, routes)
            if problem is None:
                continue
            finding = Finding(snippet, problem)
            allow = next(
                (a for a in policy.allows if a.file == rel and a.text == snippet.text), None
            )
            if allow is not None:
                used.add(allow)
                report.allowed.append(finding)
            else:
                report.findings.append(finding)
    report.stale_allows = [a for a in policy.allows if a not in used]
    return report


def main(argv: Sequence[str]) -> int:
    files = [Path(a).resolve() for a in argv] or doc_files()
    report = scan(files)
    for f in report.findings:
        print(f.render())
    for a in report.stale_allows:
        print(f"{a.file}: stale [docs_drift] allow entry, matches nothing: {a.text!r}")
    print(
        f"docs-drift: {report.checked} commands/paths checked, {len(report.findings)} false, "
        f"{len(report.allowed)} allowed as illustrative, {len(report.stale_allows)} stale allow entries"
    )
    return 1 if report.findings or report.stale_allows else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
