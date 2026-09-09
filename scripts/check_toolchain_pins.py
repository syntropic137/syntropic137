"""Every installer of a gate-critical tool must name the SAME version.

WHY THIS EXISTS (issue #1136). The workspace image pins `just` 1.58.0, hard,
with a checksum and a post-install assertion. CI installs `just` with
`extractions/setup-just` and passes no version at all, so CI runs whatever
release is newest at job-run time. The gate an agent is required to pass is a
`just` target, so "the gate passed in the workspace" and "the gate passed in
CI" were different claims about different toolchains - green in one place and
red in the other with no change to the code.

The same shape had already spread past `just`. Before this gate existed, `uv` -
which is what actually runs the unit gate (`uv run pytest`) - was installed at
four different versions in one repository:

    workspace image                      0.11.8   (pinned)
    infra/docker/images/syn-api          0.10.6   (pinned, and stale)
    packages/syn-collector               latest   (whatever built last)
    every CI job                         <none>   (whatever ran last)

Nobody introduced that on purpose. It is what happens when a version is stated
in N places and nothing compares them.

WHAT THIS CHECKS. One rule: every place that installs `just` or `uv` names the
version the workspace image ships, and so does the binary on PATH right now.
The image is the reference because it is the toolchain an agent cannot change,
and because it is already the correctly-pinned side.

WHY THE RUNNING BINARY IS CHECKED TOO, and not just the declarations. A pin is
a claim about what will be installed; it is not evidence about what IS
installed. This repo has already been burned by exactly that gap: `setup-vsa`
pinned a version while a loose cache key served a binary from months earlier,
and every green run re-saved the stale one (see the poka-yoke note in
`.github/actions/setup-vsa/action.yml`). Declarations that agree while the
binaries differ is the failure this leg, and only this leg, can see.

WHY THE FILES ARE DISCOVERED RATHER THAN LISTED. A hardcoded list of installers
is the same drift bug one level up: the new Dockerfile nobody added to the list
is the one that pins `latest`.

WHY IT LOOKS FOR INSTALLS AND NOT ONLY FOR VERSIONS. Scanning for version
strings finds a version that is wrong and misses an installer that names none -
a number that stays still, which is the harder half of this bug to see. The
onboarding script was exactly that: `sh install.sh` for `just` and for `uv`,
no version anywhere, so a scanner looking for `1.58.0` had nothing to look at
and would have reported full agreement. So each tool declares how its INSTALL
is spelled as well as how its VERSION is, and an install with no version in its
file is reported as floating.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

#: Where a provider's image is built from, by provider name.
REFERENCE_DOCKERFILE: Final = "lib/agentic-primitives/providers/workspaces/{provider}/Dockerfile"

#: Anything else in THIS repo that installs a toolchain. Submodules are excluded
#: (they are separate repositories with their own gates) apart from the
#: reference above.
INSTALLER_SUFFIXES: Final = (".sh",)
INSTALLER_NAME_PREFIX: Final = "Dockerfile"
_SKIP_DIRS: Final = frozenset({".git", ".venv", "lib", "node_modules", "target", "dist", "build"})

#: Tags that resolve to a different artifact over time. Recorded as "no version
#: stated", because `uv:latest` and a CI step with no version input are the same
#: sin spelled two ways and deserve the same message.
_FLOATING: Final = frozenset({"latest", "main", "edge", "stable", "nightly"})

_SEMVER: Final = re.compile(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?[^\s,)]*")
_PROBE_TIMEOUT_SECONDS: Final = 30


class ToolchainProbeError(RuntimeError):
    """A tool this gate covers could not be asked what version it is."""


@dataclass(frozen=True)
class Tool:
    """One tool, and every dialect its version is written in."""

    name: str
    #: Version spellings in a Dockerfile or a shell installer. Each pattern
    #: must capture a group named `version`.
    patterns: tuple[re.Pattern[str], ...]
    #: How installing this tool is spelled when no version is stated. A file
    #: that matches one of these and states no version is installing whatever
    #: is newest, which is the defect written in invisible ink.
    installs: tuple[re.Pattern[str], ...]
    #: The GitHub Action CI installs it with, and the `with:` key that pins it.
    action: str
    action_input: str
    #: How to ask the binary on PATH what it is.
    probe: tuple[str, ...]
    #: Printed on failure, so the fix does not have to be looked up.
    hint: str


TOOLS: Final[tuple[Tool, ...]] = (
    Tool(
        name="just",
        patterns=(re.compile(r"\bJUST_VERSION\s*=\s*[\"']?(?P<version>[^\s\"']+)"),),
        installs=(
            re.compile(r"just\.systems/install\.sh"),
            re.compile(r"casey/just/releases"),
            re.compile(r"\b(?:brew|cargo|apt-get)\s+install\s+(?:-\S+\s+)*just\b"),
        ),
        action="extractions/setup-just",
        action_input="just-version",
        probe=("just", "--version"),
        hint="curl -fsSL https://just.systems/install.sh | sh -s -- --tag {version}",
    ),
    Tool(
        name="uv",
        patterns=(
            re.compile(r"ghcr\.io/astral-sh/uv:(?P<version>[^\s\"'/]+)"),
            re.compile(r"\bUV_VERSION\s*=\s*[\"']?(?P<version>[^\s\"']+)"),
            re.compile(r"astral\.sh/uv/(?P<version>[0-9][^\s\"'/]*)/install\.sh"),
        ),
        installs=(
            re.compile(r"astral\.sh/uv/install\.sh"),
            re.compile(r"ghcr\.io/astral-sh/uv"),
            re.compile(r"\b(?:brew|pipx|pip)\s+install\s+(?:-\S+\s+)*uv\b"),
        ),
        action="astral-sh/setup-uv",
        action_input="version",
        probe=("uv", "--version"),
        hint="uv self update {version}   (or: curl -LsSf https://astral.sh/uv/{version}/install.sh | sh)",
    ),
)


@dataclass(frozen=True)
class Sighting:
    """One place that decides which version of `tool` gets installed."""

    tool: str
    #: Human-readable, and precise enough to open: `path:line` or `file:job`.
    where: str
    #: None when the installer names no fixed version - either it states none
    #: at all, or it states a tag that moves.
    version: str | None
    #: True for the workspace image, whose version everything else must match.
    reference: bool = False

    @property
    def stated(self) -> str:
        return self.version or "<floating>"


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _pinned(raw: str) -> str | None:
    return None if raw.lower() in _FLOATING else raw


def text_sightings(path: Path, display: str, *, reference: bool = False) -> list[Sighting]:
    """What a Dockerfile or shell installer decides about each tool.

    A version statement is a sighting. An install with no version statement
    ANYWHERE IN THAT FILE is a floating sighting - file-scoped rather than
    line-scoped because a shell script conventionally sets `UV_VERSION` at the
    top and spends it further down, and reading only the install line would
    call that unpinned. The cost of that choice, stated rather than hidden: a
    file that pins in one place and also installs unpinned in another is
    credited with the pin.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    found: list[Sighting] = []
    for tool in TOOLS:
        stated = [
            Sighting(
                tool=tool.name,
                where=f"{display}:{_line_of(text, match.start())}",
                version=_pinned(match.group("version")),
                reference=reference,
            )
            for pattern in tool.patterns
            for match in pattern.finditer(text)
        ]
        if stated:
            found.extend(stated)
            continue
        install = next(
            (m for pattern in tool.installs for m in [pattern.search(text)] if m is not None), None
        )
        if install is not None:
            found.append(
                Sighting(
                    tool=tool.name,
                    where=f"{display}:{_line_of(text, install.start())}",
                    version=None,
                    reference=reference,
                )
            )
    return found


def installer_files(root: Path) -> Iterator[Path]:
    """Dockerfiles and shell scripts in this repo, submodules excluded."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _SKIP_DIRS.intersection(path.relative_to(root).parts[:-1]):
            continue
        if path.name.startswith(INSTALLER_NAME_PREFIX) or path.suffix in INSTALLER_SUFFIXES:
            yield path


def workflow_sightings(github_dir: Path) -> list[Sighting]:
    """Every version a CI step states, and every step that states none.

    A step with no `with: version:` is recorded rather than skipped. Skipping it
    is precisely how the drift stayed invisible: an unpinned installer looks the
    same as no installer to anything that only compares the versions it finds.

    Composite actions are read as well as workflows. A composite action is where
    an unpinned installer hides best - `check_ci_parity.py` cannot see inside
    one either - and it costs one more shape to look.
    """
    found: list[Sighting] = []
    for path in sorted(github_dir.glob("workflows/*.y*ml")):
        found.extend(workflow_file_sightings(path.read_text(encoding="utf-8"), path.name))
    for path in sorted(github_dir.glob("actions/*/action.y*ml")):
        display = str(path.relative_to(github_dir).parent)
        found.extend(workflow_file_sightings(path.read_text(encoding="utf-8"), display))
    return found


def _step_groups(document: object) -> list[tuple[str, list[object]]]:
    """`(label, steps)` for both YAML shapes that carry steps.

    A workflow keys them by job; a composite action has exactly one list under
    `runs`. Normalising here is what lets one loop below read either.
    """
    if not isinstance(document, dict):
        return []
    groups: list[tuple[str, list[object]]] = []
    jobs = document.get("jobs")
    if isinstance(jobs, dict):
        groups.extend(
            (str(job_id), job["steps"])
            for job_id, job in jobs.items()
            if isinstance(job, dict) and isinstance(job.get("steps"), list)
        )
    runs = document.get("runs")
    if isinstance(runs, dict) and isinstance(runs.get("steps"), list):
        groups.append(("runs", runs["steps"]))
    return groups


def workflow_file_sightings(document_text: str, display: str) -> list[Sighting]:
    """The sightings in ONE workflow or action document. Split out for tests."""
    found: list[Sighting] = []
    for job_id, steps in _step_groups(yaml.safe_load(document_text)):
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue
            action = uses.split("@", 1)[0].strip()
            for tool in TOOLS:
                if action != tool.action:
                    continue
                inputs = step.get("with")
                raw = inputs.get(tool.action_input) if isinstance(inputs, dict) else None
                # YAML reads `version: 1.58` as a float; compare what it means,
                # not what it looks like, and let 1.58 != 1.58.0 fail as it must.
                version = _pinned(str(raw)) if raw is not None else None
                found.append(Sighting(tool.name, f"{display}:{job_id} ({tool.action})", version))
    return found


def runtime_sightings() -> list[Sighting]:
    """What the binaries on PATH actually are, here, now."""
    found: list[Sighting] = []
    for tool in TOOLS:
        try:
            result = subprocess.run(
                tool.probe,
                capture_output=True,
                text=True,
                check=False,
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            msg = f"could not run `{' '.join(tool.probe)}`: {exc}"
            raise ToolchainProbeError(msg) from exc
        if result.returncode != 0:
            msg = f"`{' '.join(tool.probe)}` exited {result.returncode}: {result.stderr.strip()[:200]}"
            raise ToolchainProbeError(msg)
        match = _SEMVER.search(result.stdout)
        if match is None:
            msg = f"`{' '.join(tool.probe)}` printed no version: {result.stdout.strip()[:200]}"
            raise ToolchainProbeError(msg)
        found.append(Sighting(tool.name, f"$ {' '.join(tool.probe)}", match.group(0)))
    return found


def reference_dockerfiles(root: Path) -> list[Path]:
    """The Dockerfile behind every workspace image THIS repo hands to agents.

    Derived from `PINNED_DIGESTS` rather than globbed over the submodule, for
    two reasons. It covers exactly the images an agent can be given, and it
    extends itself: pin a third provider and its toolchain joins this gate
    without anyone remembering to add it. agentic-primitives builds other
    provider images that this repo does not ship; those are that repo's gate to
    run, and one of them (`base`) does install uv unpinned - reported upstream
    rather than enforced from here, where the pointer to it cannot move without
    an image release.
    """
    from syn_shared.settings.workspace_images import PINNED_DIGESTS

    return [
        root / REFERENCE_DOCKERFILE.format(provider=provider.value) for provider in PINNED_DIGESTS
    ]


def collect(root: Path) -> list[Sighting]:
    """Every sighting in the repo at `root`, plus the binaries on PATH."""
    found: list[Sighting] = []
    for path in reference_dockerfiles(root):
        found.extend(text_sightings(path, str(path.relative_to(root)), reference=True))
    for path in installer_files(root):
        found.extend(text_sightings(path, str(path.relative_to(root))))
    found.extend(workflow_sightings(root / ".github"))
    found.extend(runtime_sightings())
    return found


def evaluate(sightings: Sequence[Sighting]) -> tuple[int, list[str]]:
    """The verdict. Pure, so it is testable without a repo or a subprocess."""
    lines: list[str] = []
    failures = 0

    for tool in TOOLS:
        mine = [s for s in sightings if s.tool == tool.name]
        reference = next((s.version for s in mine if s.reference and s.version), None)

        if not mine:
            failures += 1
            lines.append(f"{tool.name}: no installer found anywhere.")
            lines.append("  Either nothing installs it, or the patterns above stopped matching")
            lines.append("  the way it is written. Both are silent-pass bugs in this gate.")
            lines.append("")
            continue

        if reference is None:
            failures += 1
            lines.append(f"{tool.name}: the workspace image states no fixed version.")
            lines.append(f"  Expected a pin in {REFERENCE_DOCKERFILE}.")
            lines.append("  If lib/agentic-primitives is not checked out: just submodules-init")
            lines.append("")
            continue

        bad = [s for s in mine if s.version != reference]
        lines.append(f"{tool.name} {reference} (workspace image), {len(mine)} installer(s):")
        for s in mine:
            lines.append(f"  [{'BAD' if s.version != reference else 'OK '}] {s.stated:<10} {s.where}")
        if bad:
            failures += 1
            lines.append("")
            lines.append(f"  {len(bad)} of these do not install {tool.name} {reference}.")
            lines.append("  A gate is only one claim if every environment runs one toolchain.")
            lines.append(f"  Fix: {tool.hint.format(version=reference)}")
            lines.append(f"  In CI: pass `with: {tool.action_input}: \"{reference}\"` to {tool.action}.")
        lines.append("")

    if failures:
        lines.append(f"{failures} tool(s) are installed at more than one version. See #1136.")
        return 1, lines

    lines.append(f"Every installer of {', '.join(t.name for t in TOOLS)} agrees with the image.")
    return 0, lines


def main() -> int:
    missing = [p for p in reference_dockerfiles(REPO_ROOT) if not p.is_file()]
    if missing:
        for path in missing:
            print(f"missing workspace image Dockerfile: {path}", file=sys.stderr)
        print("The reference toolchain is unreadable; run: just submodules-init", file=sys.stderr)
        return 1
    try:
        sightings = collect(REPO_ROOT)
    except ToolchainProbeError as exc:
        print(f"{exc}", file=sys.stderr)
        print("This gate compares the binary you are running, so it must be runnable.", file=sys.stderr)
        return 1
    code, lines = evaluate(sightings)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
