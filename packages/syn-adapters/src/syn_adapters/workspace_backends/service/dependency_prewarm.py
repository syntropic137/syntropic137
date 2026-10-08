"""The setup-script lines that install a checkout's locked dependencies (#1726).

Kept beside `pinned_checkout`, and for the same reason: `SetupPhaseSecrets`
decides WHETHER these lines run, this module owns WHAT they are.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

PREWARM_TIMEOUT_SECONDS: Final[int] = 1800
"""The most one prewarm install may take, and the extra time a prewarming setup gets (#1726)."""


def append_dependency_prewarm(lines: list[str], destinations: Sequence[str]) -> None:
    """Install each clone's locked dependencies while setup still has network (#1726).

    Runs after every clone is at its pin, so what is installed is what the
    pinned commit's lockfiles say. Every installer is FROZEN: a lockfile
    that does not match its manifest fails setup rather than being
    rewritten, because a rewritten lockfile is a change in the tree the
    agent was asked to review and the unpushed-work gate would see it.

    Per lockfile found, at any depth below the checkout (submodules
    included; dependency, build and VCS directories excluded):

    - ``uv.lock``: ``uv sync --frozen``, the environment ``uv run`` uses.
    - ``pnpm-lock.yaml``: ``pnpm install --frozen-lockfile``, through
      corepack when pnpm itself is not on PATH.
    - ``Cargo.lock``: ``cargo fetch --locked``, so a later ``cargo build
      --locked`` needs no network. With no cargo but a rustup, the stable
      minimal toolchain is installed first - the step
      ``scripts/agent-fitness.sh`` would otherwise take offline and fail.

    A tool the image does not have is skipped with a line on stderr, not
    failed: the agent cannot run that tool either, so there is nothing to
    warm for it. A step that runs and fails, or outlives
    ``PREWARM_TIMEOUT_SECONDS``, fails setup (``set -e``), so no agent
    starts against half a dependency tree. TMPDIR moves under /workspace
    because /tmp is mounted noexec in the workspace image (#1100).
    """

    budget = PREWARM_TIMEOUT_SECONDS
    roots = " ".join(shlex.quote(dest) for dest in destinations)
    lines.extend(
        [
            "",
            "# Install the clones' locked dependencies while setup has network (#1726)",
            "export TMPDIR=/workspace/.tmp",
            'mkdir -p "$TMPDIR"',
            "syn_locks() {",
            f"    find {roots} \\( -name node_modules -o -name target -o -name .venv"
            ' -o -name .git \\) -prune -o -name "$1" -type f -print | sort',
            "}",
            "syn_locks uv.lock | while read -r lock; do",
            "    if ! command -v uv >/dev/null 2>&1; then",
            '        echo "prewarm: no uv on PATH; not installing $lock" >&2; continue',
            "    fi",
            '    echo "prewarm: uv sync --frozen in ${lock%/*}"',
            f'    (cd "${{lock%/*}}" && timeout {budget} uv sync --frozen)',
            "done",
            "syn_locks pnpm-lock.yaml | while read -r lock; do",
            "    if command -v pnpm >/dev/null 2>&1; then syn_pnpm=pnpm",
            "    elif command -v corepack >/dev/null 2>&1; then syn_pnpm='corepack pnpm'",
            "    else",
            '        echo "prewarm: no pnpm or corepack on PATH; not installing $lock" >&2',
            "        continue",
            "    fi",
            '    echo "prewarm: pnpm install --frozen-lockfile in ${lock%/*}"',
            f'    (cd "${{lock%/*}}" && timeout {budget} $syn_pnpm install --frozen-lockfile)',
            "done",
            'if [ -n "$(syn_locks Cargo.lock)" ] && ! cargo --version >/dev/null 2>&1'
            " && command -v rustup >/dev/null 2>&1; then",
            '    echo "prewarm: installing the stable Rust toolchain"',
            f"    timeout {budget} rustup toolchain install stable --profile minimal"
            " --no-self-update",
            "fi",
            "syn_locks Cargo.lock | while read -r lock; do",
            '    [ -f "${lock%/*}/Cargo.toml" ] || continue',
            "    if ! cargo --version >/dev/null 2>&1; then",
            '        echo "prewarm: no cargo; not fetching crates for $lock" >&2; continue',
            "    fi",
            '    echo "prewarm: cargo fetch --locked for ${lock%/*}"',
            f'    timeout {budget} cargo fetch --locked --manifest-path "${{lock%/*}}/Cargo.toml"',
            "done",
        ]
    )
