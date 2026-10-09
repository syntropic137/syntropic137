"""Whether an agent's tool call is POSITIVELY known to change nothing (#1825).

The fallback rule (PC-83) needs to know whether a failed attempt may have done
WORK: changed something a second agent, run from the top in the same
workspace, would then do again. Reading a file, searching a tree or viewing a
diff is not work in that sense. A review that read twenty files and was then
refused leaves the workspace exactly as it found it, so a restart on another
agent duplicates nothing and loses nothing.

ASKED IN THE DIRECTION THAT FAILS SAFE, like `_phase_got_somewhere`: the
claim made here is the strong one, "this changed nothing", and it is made only
for shapes recognised in full. A command this module cannot read completely is
work. That covers a redirect, a substitution, an interpreter, a tool it has no
entry for, and any argument it does not understand. The cost of a false "work"
is a fallback that does not run, which is what happened before this module. The
cost of a false "nothing" is a second agent writing over the first agent's
changes, so the asymmetry is deliberate.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

from syn_shared.codex_stream import CodexItemType

#: Claude tools that only read. Anything not listed is treated as work.
READ_ONLY_TOOLS: frozenset[str] = frozenset({"Read", "Grep", "Glob", "LS"})

#: The shell-tool names both harnesses report (codex `command_execution` is
#: recorded as ``Bash`` too). The command decides for these.
SHELL_TOOLS: frozenset[str] = frozenset({"Bash"})

#: Programs that read, whatever their arguments, short of a redirect (refused
#: below for every program). `sed`, `find`, `git` and `gh` are absent on
#: purpose: each has a writing mode and is decided in `_segment_reads`. `rg` is
#: decided there too: ``RIPGREP_CONFIG_PATH`` can add ``--pre``. So are
#: `sort -o`, `uniq IN OUT` and `tree -o`, which write a file by argument.
_READ_ONLY_PROGRAMS: frozenset[str] = frozenset(
    {
        "cat", "head", "tail", "grep", "egrep", "fgrep", "ls", "wc", "nl",
        "pwd", "echo", "cd", "stat", "file", "diff", "which", "true", "cut",
        "tr", "jq", "basename", "dirname", "realpath",
    }
)  # fmt: skip

#: `git` subcommands that read the repository and never move a ref, each with
#: the switches that stop it running a program git CONFIGURATION names. Git
#: reads that configuration when the command runs, wherever it came from: a
#: driver installed before the attempt runs inside the attempt's plain `git
#: diff` all the same, so only an invocation that switches it off is certified.
#: ``diff`` runs ``diff.external`` / ``GIT_EXTERNAL_DIFF`` and textconv filters
#: by default; ``log`` and ``show`` run textconv and ``gpg.program`` (for
#: ``log.showSignature``); ``blame`` runs textconv. `status` is absent: it
#: runs ``core.fsmonitor`` and no option turns that off.
_READ_ONLY_GIT: dict[str, frozenset[str]] = {
    "diff": frozenset({"--no-ext-diff", "--no-textconv"}),
    "log": frozenset({"--no-ext-diff", "--no-textconv", "--no-show-signature"}),
    "show": frozenset({"--no-ext-diff", "--no-textconv", "--no-show-signature"}),
    "blame": frozenset({"--no-textconv"}),
    "rev-parse": frozenset(),
    "ls-files": frozenset(),
    "grep": frozenset(),
    "cat-file": frozenset(),
}

#: Before the subcommand, the switch that stops ANY git command running the
#: configured pager (``core.pager``, ``GIT_PAGER``, ``pager.<cmd>``).
_GIT_NO_PAGER: frozenset[str] = frozenset({"--no-pager", "-P"})

#: `gh` subcommand pairs that only read from GitHub.
_READ_ONLY_GH: frozenset[tuple[str, str]] = frozenset(
    {("pr", "view"), ("pr", "diff"), ("pr", "list"), ("pr", "checks"), ("issue", "view"),
     ("issue", "list"), ("run", "view"), ("run", "list")}
)  # fmt: skip

#: Shell syntax that can write or run something this module cannot see. A
#: redirect to /dev/null is removed before this is asked, since it writes
#: nowhere anyone reads. A lone ``&`` backgrounds what precedes it and starts
#: a new command after it, so it is refused rather than parsed: read as an
#: argument, ``echo x & touch y`` would hide the write inside echo's arguments.
_UNREADABLE_SYNTAX = re.compile(r"[>`]|\$\(|<\(|\btee\b|(?<!&)&(?!&)")
#: The target must be /dev/null EXACTLY: ``> /dev/null-out`` writes a file.
_DEV_NULL_REDIRECT = re.compile(r"\d?>>?\s*/dev/null(?![^\s;&|])|\d>&\d")
_SEGMENT_SEPARATOR = re.compile(r"\|\|?|&&|;|\n")
_SHELLS: frozenset[str] = frozenset({"sh", "bash", "zsh"})


def tool_call_changes_nothing(tool_name: str, command: object = None) -> bool:
    """Whether a call to ``tool_name`` is known to leave the workspace as it was.

    ``command`` is read only for a shell tool, and must be the WHOLE command, not
    a truncated preview: a preview can end before the part that writes.
    """
    if tool_name in READ_ONLY_TOOLS:
        return True
    if tool_name in SHELL_TOOLS:
        return isinstance(command, str) and command_changes_nothing(command)
    return False


#: Codex item types that are the model's words, so can change nothing.
#: ``reasoning`` is codex's summarised thinking; nothing else in the platform
#: reads it, so it has no `CodexItemType` member.
_CODEX_WORDS_ONLY_ITEMS: frozenset[str] = frozenset({CodexItemType.AGENT_MESSAGE, "reasoning"})


def codex_item_changes_nothing(item_type: object, command: object) -> bool:
    """Whether a codex item is known to leave the workspace as it was.

    Words, and a ``command_execution`` whose command reads in full. Every
    other type, ``file_change`` and types not yet known included, may have
    written.
    """
    if item_type in _CODEX_WORDS_ONLY_ITEMS:
        return True
    if item_type == CodexItemType.COMMAND_EXECUTION:
        return isinstance(command, str) and command_changes_nothing(command)
    return False


def command_changes_nothing(command: str) -> bool:
    """Whether a shell command line is known to only read."""
    script = _unwrap_shell(command)
    if script is None:
        return False
    script = _DEV_NULL_REDIRECT.sub(" ", script)
    if _UNREADABLE_SYNTAX.search(script):
        return False
    segments = [s for s in _SEGMENT_SEPARATOR.split(script) if s.strip()]
    return bool(segments) and all(_segment_reads(s) for s in segments)


def _unwrap_shell(command: str) -> str | None:
    """The script a ``/bin/zsh -lc '...'`` wrapper runs, or the command itself."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if len(words) == 3 and PurePosixPath(words[0]).name in _SHELLS and words[1] in {"-c", "-lc"}:
        return words[2]
    return command


#: Options that make an otherwise reading program write a file or run another
#: one, whichever program carries them: `git diff --output`, `rg --pre`.
_WRITING_OPTIONS: tuple[str, ...] = ("--output", "--pre")

#: Options that make a reading git subcommand RUN another program: an external
#: diff driver, a textconv filter, a pager for the matched files. What git runs
#: from configuration alone is switched off by `_READ_ONLY_GIT`'s switches.
_GIT_EXECUTING_OPTIONS: tuple[str, ...] = (
    "--ext-diff", "--textconv", "--filters", "--open-files-in-pager", "-O",
)  # fmt: skip

#: `find` actions that run, delete or write (`-fprint`, `-fls`).
_FIND_ACTIONS: tuple[str, ...] = ("-exec", "-ok", "-delete", "-fprint", "-fls")


def _segment_reads(segment: str) -> bool:
    try:
        words = shlex.split(segment)
    except ValueError:
        return False
    if not words:
        return False
    program, args = PurePosixPath(words[0]).name, words[1:]
    if any(a.startswith(_WRITING_OPTIONS) for a in args):
        return False
    if program in _READ_ONLY_PROGRAMS:
        return True
    if program == "sed":
        return _sed_prints(args)
    if program == "find":
        return not any(a.startswith(_FIND_ACTIONS) for a in args)
    if program == "git":
        return _git_reads(args)
    if program == "rg":
        return "--no-config" in args
    if program == "gh":
        return len(args) >= 2 and (args[0], args[1]) in _READ_ONLY_GH
    return False


#: A sed script that only prints a line range, the one shape agents read with.
_SED_PRINT = re.compile(r"[0-9]+(,[0-9$]+)?p")


def _sed_prints(args: list[str]) -> bool:
    """``sed -n 1,80p FILE...``: options limited to -n/-E/-r, the script a print."""
    scripts = [a for a in args if not a.startswith("-")]
    return (
        all(a in {"-n", "-E", "-r"} for a in args if a.startswith("-"))
        and bool(scripts)
        and _SED_PRINT.fullmatch(scripts[0]) is not None
    )


def _git_reads(args: list[str]) -> bool:
    """A read-only git subcommand that can run no program, configured or named.

    The pager is switched off before the subcommand, every switch
    `_READ_ONLY_GIT` lists for it is present, and no option runs a program.
    """
    index = _git_subcommand_index(args)
    if index is None or args[index] not in _READ_ONLY_GIT:
        return False
    switches = set(args[index + 1 :])
    return (
        not _GIT_NO_PAGER.isdisjoint(args[:index])
        and _READ_ONLY_GIT[args[index]] <= switches
        and not any(a.startswith(_GIT_EXECUTING_OPTIONS) for a in args)
    )


def _git_subcommand_index(args: list[str]) -> int | None:
    """Where the git subcommand is, after any ``-C <dir>`` / ``--no-pager`` options."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-C":
            index += 2
        elif arg in _GIT_NO_PAGER:
            index += 1
        elif arg.startswith("-"):
            return None
        else:
            return index
    return None
