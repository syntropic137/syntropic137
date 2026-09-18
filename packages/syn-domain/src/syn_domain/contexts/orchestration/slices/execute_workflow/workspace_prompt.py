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
gate could not actually be switched on - turning it on sent the agent looking
for a checkout that was never made.

WHAT WAS NEVER THE PROBLEM: a missing directory. `/workspace/repos` always
exists. Both workspace images pre-create it and the entrypoint creates it again
unconditionally, and `unpushed_work_guard._repositories` depends on exactly that
to read an empty result as "this phase cloned nothing" rather than "the
workspace did not answer". So the no-checkout tree below shows the directory,
empty - describing it as absent would put the prompt in contradiction with an
invariant production relies on. The synthetic `CLAUDE.md`/`AGENTS.md` the tree
also advertised ARE absent for such a phase
(`WorkspaceProvisionHandler._hydrate_workspace`). Empty and missing are
different claims and the tree has to keep them apart.

The claims are now made per phase, by the one caller that knows the answer. A
phase that DOES clone gets exactly the bytes it got before - see
``test_open_pr_needs_no_working_tree`` for the frozen baseline that pins this.

WHY "Completing Your Task" STATES THE DELIVERABLE UNCONDITIONALLY (#1221). The
instruction to write ``artifacts/output/deliverable.md`` used to be step 4 of a
four-step action sequence, and every field it asked for presupposed that the
first three steps had happened: "what you actually changed", "your actual
commit hashes", "the actual PR URL you created". A phase whose honest answer is
"nothing needed doing" could satisfy none of them, and the sequence gave it no
instruction at all for that case - so it reported nothing. `open_pr` did
exactly this on 6 of 100 executions: it investigated, found the PR already
open at the verified head, correctly declined to open a second one, and exited
without writing. The execution then failed on `PhaseProducedNoDeclaredOutputError`
(#1167) with the work intact and verification already passed.

The requirement therefore comes BEFORE the coding/non-coding split, applies to
both, and names the no-action outcome as one of four reportable ones. This is
the phase's contract rather than its prompt, which is the half of #1221's
"decide which" that does not have to wait on the frozen `workflows/` baseline -
and being here it covers every phase of every workflow, not just the four
copies of ``open_pr.md``.

NOT a relaxation of #1167. That check still fails a phase that writes nothing,
and must: it is what catches a phase that silently did nothing. This removes
the reason a correct phase had to trip it, rather than teaching the check to
look away.

WHY THE RESULT BLOCK IS ONE COMPLETE FENCE PER OUTCOME (#1324). #1256 made
``TASK_RESULT_END`` mandatory and this prompt was not updated to match, so the
only fence carrying the terminator carried no JSON, and the two fences carrying
JSON carried no terminator. An agent copying either one could not arrive at a
complete block: the parts were in different fences and it had to assemble them.
exec-138d516b91e8 wrote valid JSON, omitted the terminator and lost the run;
three runs and $20.44 in forty minutes went the same way.

So each outcome gets one fence holding the whole block - marker, literal JSON
and terminator already on its own line - and the fences are the last instruction
before the sign-off, because the rule they state is about the last thing in the
reply. The consequence of dropping the terminator is stated immediately ABOVE
them rather than in a paragraph below, since an agent that skims to the first
code fence never reads what follows the examples.

WHY THE JSON IS LITERAL, AND WHAT THAT COSTS. A first fix for #1324 kept the
fences unparseable by making ``comments`` a ``<"...">`` slot, so that quoting
the prompt could never be mistaken for obeying it. That reintroduces the defect
it was meant to fix, one step later: an agent that copies the fence UNCHANGED
has written no readable verdict and loses the run, which is the same lost run as
before, now charged to faithful copying rather than to assembly.

The two properties cannot both hold, and this is worth stating plainly because
it is the first thing the next reader will try to fix. A fence that is copyable
verbatim IS, by construction, byte-identical to a real report; `phase_verdict`
is delimited rather than located, so it cannot tell a pasted block from a quoted
one - there is nothing to tell apart. "Copyable verbatim" and "inert when
quoted" are therefore mutually exclusive, and no wording recovers both.

WHICH SIDE THIS TAKES, AND WHY IT IS SAFE. The literal side, because the two
costs are not the same size and not the same kind:

  - The slot charges EVERY agent on EVERY phase a substitution step, on the
    common path where the work was done and only the report is left. That is
    the step #1324 exists because agents demonstrably get wrong.
  - Literal JSON charges only an agent that closes a SECOND complete block it
    did not mean as its report. Under `phase_verdict`'s precedence
    (FAILURE > SUCCESS) that resolves to FAILURE.

Both are fail-closed, and that is the property that makes the trade safe rather
than merely cheaper. Quoting this prompt can only move a verdict UP the
precedence, toward refusal; it can never manufacture a completion, and it can
never take back a reported failure - which is the whole of what #1256 exists to
protect. The prompt therefore says outright that a closed block is a report
wherever it sits and that only one may be written, since reducing how often that
second block gets closed is the part still available to the emitter.

Pinned by test in `test_reported_failure_stays_a_failure.py`: that each fence
copied VERBATIM is a verdict of the right polarity - the acceptance criterion of
#1324 - and that the rendered prompt, read whole by the production reader, never
yields SUCCESS.
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

#: `repos/` is present and EMPTY - the directory is always created, only the
#: checkout beneath it is conditional. No synthetic CLAUDE.md/AGENTS.md though:
#: both are derived from what was actually cloned, so neither exists here.
_TREE_WITHOUT_CHECKOUT: Final[str] = """\
/workspace/
├── artifacts/
│   ├── input/   ← Previous phase outputs (read-only)
│   └── output/  ← Write YOUR deliverables here
└── repos/       ← Exists but EMPTY - nothing is checked out for this phase"""

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

**The deliverable is not conditional on having acted.** `artifacts/output/` is
how a phase reports, so it is written for every outcome:

- **you did the work** - describe what you changed and where it is
- **it was already done, or turned out not to be needed** - say so, and show
  what you checked that established it
- **you declined to act**, because acting would have been wrong - say why
- **you could not act** - say what stopped you

"Nothing needed doing" is a conclusion, and the evidence behind it is the
deliverable. Reaching it and writing no file reports nothing at all: from
outside it is indistinguishable from a phase that ran and produced nothing,
and that fails the execution.

### For coding tasks (commits, PRs, code changes):

Your primary deliverable is **code on GitHub**. The artifact is your summary.

{_STARTING_POINT_SLOT}
2. Make changes, commit with clear messages
3. Push to GitHub, create PR if needed
4. Write summary to `artifacts/output/deliverable.md` with:
   - What you actually changed, or what you found already correct
   - Your actual commit hashes, if you made any
   - The actual PR URL - the one you opened, or the one that was already there
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

**The very last thing in your response must be a `TASK_RESULT` block.** It is
three parts - the marker, one JSON object, and `TASK_RESULT_END` on the line
after it - and it is read as your result only when all three are there.

A failure reason is specific. What a useful one looks like:
- "GitHub App not installed on repo org/repo — cannot clone or push"
- "Repository org/repo does not exist or is not accessible"
- "Pull request #42 was not found"
- "Required environment variable GH_TOKEN is not set"

Write ONE complete block, for your outcome only. A complete block is read as
your report wherever it sits, so do not copy out the other one to explain the
format - once it is closed it is a report and not a quotation, whatever the
words around it say. Discussing the format in prose is free; closing a second
block is not.

Copy the ONE block below that matches your outcome - both lines - and replace
the `comments` text with your own. **Write both lines. A block whose
`TASK_RESULT_END` line is missing is failed as UNREADABLE instead of completed,
so stopping after the JSON loses the run.**

You completed the task - copy both lines:

```
TASK_RESULT: {{"success": true, "comments": "Brief summary of what was accomplished"}}
TASK_RESULT_END
```

You could NOT complete the task, because you were blocked, lacked access, or hit
an error - copy both lines:

```
TASK_RESULT: {{"success": false, "comments": "Specific reason why — what was missing or what failed"}}
TASK_RESULT_END
```

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
