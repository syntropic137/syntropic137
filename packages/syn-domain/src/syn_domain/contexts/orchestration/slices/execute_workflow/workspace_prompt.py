"""Syn137 Workspace prompt for artifact output instructions.

Previously provided by agentic-primitives' agentic_workspace package (ADR-012).
Inlined here after agentic_workspace was removed in agentic-primitives v3.1.0.

The prompt defines the contract between Syn137 orchestrators and agents running
in containerized workspaces. It instructs agents on workspace structure,
artifact output, and critical rules.

WHY THIS RENDERS RATHER THAN EXPORTING A CONSTANT (#1187). A phase can declare
`clone_repos: false` when what it needs is credentials, not a checkout. For such
a phase this prompt used to state two things that are false: that `repos/` holds
pre-cloned repositories, and that the way to start work is to navigate into
`/workspace/repos/<name>`. Both were unconditional, so the merged `clone_repos`
gate could not actually be switched on - turning it on told the agent to enter a
directory that does not exist, and the synthetic `CLAUDE.md`/`AGENTS.md` the tree
also advertised are not injected for such a phase either
(`WorkspaceProvisionHandler._hydrate_workspace`).

The claims are now made per phase, by the one caller that knows the answer. A
phase that DOES clone gets exactly the bytes it got before - see
``test_open_pr_needs_no_working_tree`` for the frozen baseline that pins this.
"""

from __future__ import annotations

from typing import Final

#: Placeholders, not f-string fields or ``str.format`` slots: the prompt is full
#: of literal braces (``{repo-name}``, the TASK_RESULT JSON) that either of those
#: would require escaping throughout, and the escaping - not the prose - is where
#: a byte goes missing. These two are the ONLY places the prompt makes a claim
#: about whether the repository is on disk.
_TREE_SLOT: Final[str] = "@@WORKSPACE_TREE@@"
_STARTING_POINT_SLOT: Final[str] = "@@WHERE_THE_CODE_IS@@"

_TREE_WITH_CHECKOUT: Final[str] = """\
/workspace/
├── CLAUDE.md    ← @-imports each repo's CLAUDE.md (loaded automatically)
├── AGENTS.md    ← @-imports each repo's AGENTS.md (same content)
├── artifacts/
│   ├── input/   ← Previous phase outputs (read-only)
│   └── output/  ← Write YOUR deliverables here
└── repos/       ← Pre-cloned repositories (ready to use)
    └── {repo-name}/"""

#: No `repos/`, and no synthetic CLAUDE.md/AGENTS.md either - both are derived
#: from what was actually cloned, so neither exists for this phase.
_TREE_WITHOUT_CHECKOUT: Final[str] = """\
/workspace/
└── artifacts/
    ├── input/   ← Previous phase outputs (read-only)
    └── output/  ← Write YOUR deliverables here"""

_STARTING_POINT_WITH_CHECKOUT: Final[str] = (
    "1. Navigate to `/workspace/repos/{repo-name}` (repositories are "
    "**pre-cloned** — do not run `git clone`), create a feature branch"
)

#: Names only what the setup phase actually provisions for a no-checkout phase:
#: per-repo git credentials, a `gh` hosts.yml entry, and `GH_REPO`. Nothing else
#: - an agent that acts on a capability this prompt invented has no way to find
#: out it was not there until the command fails.
_STARTING_POINT_WITHOUT_CHECKOUT: Final[str] = """\
1. **This phase has no checkout.** The repository is not on disk: there is no
   working tree to enter, to commit in, or to push from. What you have instead
   is credentials - git credentials for the repository, an authenticated `gh`,
   and `GH_REPO` set to its `owner/repo` so that `gh` resolves the repository
   without a working tree to infer it from. Do the GitHub work through `gh`
   from wherever you are. If the task genuinely needs a checkout, say so and
   stop rather than cloning one: the phase declared it did not need one, and
   that mismatch is the useful thing to report."""

_TEMPLATE: Final[str] = f"""\
## Syn137 Workspace Environment

You are an agent running in an ephemeral Docker workspace managed by Syntropic137.

### Workspace Structure

```
{_TREE_SLOT}
```

---

## Critical Rules

1. **Write your actual work to `artifacts/output/`** - this is the ONLY directory collected
2. **NEVER write placeholder text** - no "...", "[Title]", or template text
3. **Every artifact must contain real content** you created for this specific task
4. **Check `artifacts/input/` first** if this is not the first phase

---

## Completing Your Task

### For coding tasks (commits, PRs, code changes):

Your primary deliverable is **code on GitHub**. The artifact is your summary.

{_STARTING_POINT_SLOT}
2. Make changes, commit with clear messages
3. Push to GitHub, create PR if needed
4. Write summary to `artifacts/output/deliverable.md` with:
   - What you actually changed
   - Your actual commit hashes
   - The actual PR URL you created
   - Brief executive summary

### For non-coding tasks (research, analysis, design, planning):

Your primary deliverable is **the content in `artifacts/output/`**.

Write your actual findings, analysis, or plan to `artifacts/output/deliverable.md`.
Structure it appropriately for the task (summary, findings, recommendations, etc.).

---

## Reading Previous Phase Outputs

Check for inputs from previous phases:

```bash
ls /workspace/artifacts/input/
cat /workspace/artifacts/input/*.md
```

Build on this context. If the input contains only placeholder text,
the previous phase failed - report this in your output.

---

## Important

- **Ephemeral workspace** - all files destroyed when session ends
- **Only `artifacts/output/` collected** - everything else is lost
- **Push code before session ends** - unpushed commits are lost
- **Use feature branches** - never push directly to main/master
- **Write REAL content** - never copy example templates literally

---

## Task Result (REQUIRED)

**The very last thing in your response must be a `TASK_RESULT` block.**

If you completed the task successfully:
```
TASK_RESULT: {{"success": true, "comments": "Brief summary of what was accomplished"}}
```

If you could NOT complete the task (blocked, missing access, error, etc.):
```
TASK_RESULT: {{"success": false, "comments": "Specific reason why — what was missing or what failed"}}
```

Examples of failure reasons:
- "GitHub App not installed on repo org/repo — cannot clone or push"
- "Repository org/repo does not exist or is not accessible"
- "Pull request #42 was not found"
- "Required environment variable GH_TOKEN is not set"

This is how the orchestrator knows whether to retry, escalate, or mark the task as done."""


def render_workspace_prompt(*, clone_repos: bool) -> str:
    """The workspace contract, stated truthfully for one phase.

    Args:
        clone_repos: Whether this phase's workspace has the repositories checked
            out - ``ExecutablePhase.clone_repos``. False means the repos were
            credentialed but never cloned (#1187).

    Returns:
        The prompt preamble prepended to every phase prompt.
    """
    tree = _TREE_WITH_CHECKOUT if clone_repos else _TREE_WITHOUT_CHECKOUT
    starting_point = (
        _STARTING_POINT_WITH_CHECKOUT if clone_repos else _STARTING_POINT_WITHOUT_CHECKOUT
    )
    return _TEMPLATE.replace(_TREE_SLOT, tree).replace(_STARTING_POINT_SLOT, starting_point)
