"""Docker-gated pin-drift guard for the skills CLI inside the omni-agent image.

Per-phase skill injection (issue #772) works by running

    skills add /workspace/.syn-skills/<name> --agent <key> -y

inside the workspace container, with ``cwd=/workspace``. Everything downstream
of that call is owned by the vercel skills CLI, which is pinned at 1.5.14 in
the image. The one thing that actually differs per harness is the directory the
skill lands in:

    --agent claude-code  ->  /workspace/.claude/skills/<name>
    --agent codex        ->  /workspace/.agents/skills/<name>

That install path is the real discriminator and the only thing that proves a
skill reaches the agent the phase drives.

TRAP, verified empirically against 1.5.14: ``skills list --agent <key>`` DOES
NOT FILTER. ``--agent claude-code`` and ``--agent codex`` return byte-identical
full listings, so an assertion built on that flag passes even when the skill
was installed for the WRONG harness. This test never asserts on it. It asserts
on the on-disk path, on the ``path`` field of ``skills list --json``, and on
``skills-lock.json``.

This is a pin-drift guard, not a behavioral test of Syntropic137 code: it fails
loudly if the skills CLI moves off 1.5.14 or changes its per-agent layout, so a
digest bump in ``workspace_images.py`` cannot silently break skill injection.

Gating mirrors the docker-gated pattern used elsewhere in this package: skip
cleanly when docker is absent or when the pinned image is not already present
on the host (we never pull a multi-GB image implicitly).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import Final, TypedDict

import pytest

from syn_shared.settings.workspace_images import (
    WorkspaceImageProvider,
    workspace_image_ref,
)

# The skills CLI version the injection contract was verified against. A bump
# here is a deliberate act: re-verify install paths before changing it.
EXPECTED_SKILLS_CLI_VERSION: Final[str] = "1.5.14"

# Where each --agent key installs a project-scoped skill, relative to /workspace.
CLAUDE_CODE_SKILL_ROOT: Final[str] = ".claude/skills"
CODEX_SKILL_ROOT: Final[str] = ".agents/skills"

OMNI_IMAGE: Final[str] = workspace_image_ref(WorkspaceImageProvider.OMNI_AGENT)

REASON_NO_DOCKER: Final[str] = "docker not available on host"
REASON_NO_IMAGE: Final[str] = f"pinned omni-agent image not present on host: {OMNI_IMAGE}"

_DOCKER_RUN_TIMEOUT_SECONDS: Final[int] = 300

_MARKER_VERSION: Final[str] = "###VERSION###"
_MARKER_PATHS: Final[str] = "###PATHS###"
_MARKER_LOCK: Final[str] = "###LOCK###"
_MARKER_LIST: Final[str] = "###LIST###"


def _docker_present() -> bool:
    return shutil.which("docker") is not None


def _image_present(ref: str) -> bool:
    if not _docker_present():
        return False
    result = subprocess.run(
        ["docker", "image", "inspect", ref],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


class SkillsLockEntry(TypedDict, total=False):
    """One skill's record in ``/workspace/skills-lock.json``."""

    source: str
    sourceType: str  # noqa: N815 - the skills CLI emits camelCase
    computedHash: str  # noqa: N815


class SkillsLockFile(TypedDict, total=False):
    """Wire shape of ``skills-lock.json`` as the skills CLI writes it."""

    version: int
    skills: dict[str, SkillsLockEntry]


class SkillsListEntry(TypedDict, total=False):
    """One entry from ``skills list --json``.

    ``path`` is the load-bearing field: it is the ONLY reliable discriminator
    between harnesses, because ``--agent`` does not filter the listing.
    """

    name: str
    path: str
    scope: str
    agents: list[str]


@dataclass(frozen=True)
class SkillsCliProbe:
    """Everything the in-container probe observed after one ``skills add``."""

    version: str
    installed_paths: tuple[str, ...]
    lock: SkillsLockFile
    listing: tuple[SkillsListEntry, ...]


def _probe_script(skill_name: str, agent_key: str) -> str:
    """Bash run inside the container: seed a skill, install it, report facts.

    The fixture skill is written inside the container rather than bind-mounted
    so the test needs no writable host path and no ownership juggling.
    """
    return f"""
set -euo pipefail
mkdir -p /workspace/.syn-skills/{skill_name}
cat > /workspace/.syn-skills/{skill_name}/SKILL.md <<'SKILLEOF'
---
name: {skill_name}
description: Fixture skill asserting per-agent install semantics.
---

Reply with the literal string VERIFIED.
SKILLEOF
cd /workspace
echo "{_MARKER_VERSION}"
skills --version
skills add /workspace/.syn-skills/{skill_name} --agent {agent_key} -y >/dev/null 2>&1
echo "{_MARKER_PATHS}"
# Every place a project-scoped skill could have landed. Printing all of them
# (not just the expected one) is what makes the cross-harness negative
# assertion possible.
for root in {CLAUDE_CODE_SKILL_ROOT} {CODEX_SKILL_ROOT}; do
  if [ -d "/workspace/$root/{skill_name}" ]; then echo "$root"; fi
done
echo "{_MARKER_LOCK}"
cat /workspace/skills-lock.json
echo "{_MARKER_LIST}"
skills list --json
"""


def _section(stdout: str, marker: str) -> str:
    """Text between ``marker`` and the next marker (or end of output)."""
    _, _, rest = stdout.partition(marker + "\n")
    for other in (_MARKER_VERSION, _MARKER_PATHS, _MARKER_LOCK, _MARKER_LIST):
        head, sep, _ = rest.partition(other + "\n")
        if sep:
            rest = head
    return rest.strip()


def _run_probe(skill_name: str, agent_key: str) -> SkillsCliProbe:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "bash",
            OMNI_IMAGE,
            "-c",
            _probe_script(skill_name, agent_key),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=_DOCKER_RUN_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"probe container failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    paths_section = _section(result.stdout, _MARKER_PATHS)
    return SkillsCliProbe(
        version=_section(result.stdout, _MARKER_VERSION),
        installed_paths=tuple(line for line in paths_section.splitlines() if line),
        lock=json.loads(_section(result.stdout, _MARKER_LOCK)),
        listing=tuple(json.loads(_section(result.stdout, _MARKER_LIST))),
    )


@pytest.mark.integration
@pytest.mark.skipif(not _docker_present(), reason=REASON_NO_DOCKER)
@pytest.mark.skipif(not _image_present(OMNI_IMAGE), reason=REASON_NO_IMAGE)
@pytest.mark.parametrize(
    ("agent_key", "expected_root", "other_root"),
    [
        ("claude-code", CLAUDE_CODE_SKILL_ROOT, CODEX_SKILL_ROOT),
        ("codex", CODEX_SKILL_ROOT, CLAUDE_CODE_SKILL_ROOT),
    ],
)
def test_skills_add_installs_under_the_agent_specific_root(
    agent_key: str,
    expected_root: str,
    other_root: str,
) -> None:
    """``skills add --agent <key>`` lands the skill under that agent's root only."""
    # Unique per run, so a collision with a skill baked into the image is
    # impossible and a stale layer cannot make this pass.
    skill_name = f"syn-verify-{uuid.uuid4().hex[:8]}"

    probe = _run_probe(skill_name, agent_key)

    assert probe.version == EXPECTED_SKILLS_CLI_VERSION, (
        f"skills CLI moved from {EXPECTED_SKILLS_CLI_VERSION} to {probe.version}. "
        "Re-verify the per-agent install paths inside the image, then update "
        "EXPECTED_SKILLS_CLI_VERSION and _SKILLS_CLI_AGENT_KEYS if the layout changed."
    )

    assert expected_root in probe.installed_paths, (
        f"--agent {agent_key} did not install under /workspace/{expected_root}; "
        f"found roots: {probe.installed_paths}"
    )
    assert other_root not in probe.installed_paths, (
        f"--agent {agent_key} also installed under /workspace/{other_root}; "
        "the per-agent install path is no longer a discriminator"
    )

    # `skills list --json` must agree with the filesystem. Note the deliberate
    # absence of any `--agent` filter assertion: that flag does not filter.
    entry = next((item for item in probe.listing if item.get("name") == skill_name), None)
    assert entry is not None, f"{skill_name} missing from `skills list --json`: {probe.listing}"
    assert entry["path"] == f"/workspace/{expected_root}/{skill_name}"
    assert entry["scope"] == "project"

    lock_skills = probe.lock["skills"]
    assert isinstance(lock_skills, dict)
    assert skill_name in lock_skills, f"skills-lock.json missing {skill_name}: {probe.lock}"
    lock_entry = lock_skills[skill_name]
    assert isinstance(lock_entry, dict)
    computed_hash = lock_entry.get("computedHash")
    assert isinstance(computed_hash, str) and len(computed_hash) == 64, (
        f"expected a sha256 computedHash for {skill_name}, got {computed_hash!r}"
    )
