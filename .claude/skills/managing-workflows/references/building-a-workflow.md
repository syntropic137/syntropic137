# Building a workflow or an A/B arm

YAML mechanics (keys, agent blocks, `prompt_file`, inputs) are in
`authoring-workflows`. This file covers the engineering decisions around them.

## Reuse, extend or create

`docs/experiments/CURRENT-BESTS.md` sets the order:

1. **Reuse** an existing workflow when it fits. This is the default.
2. **Extend** with a sibling arm (`-v4-precheck`) when the experiment varies
   one dimension. Say which dimension in the `description`.
3. **Create** only when no existing shape fits.

Prune arms after their finding lands. A suite full of stale variants hides
which one is real.

## Design rules

- **One job per phase.** Separate phases get their own workspace, tools, model
  and cost line, which makes "did this phase earn its money?" answerable.
- **The id is immutable once run.** Runs reference it. Change means `-vN+1` or
  a named arm in the same family directory.
- **Prompt files are named for their phase id.** A later phase reads
  `artifacts/input/<phase-id>.md`, so a renamed id with a stale prompt reads an
  empty directory and reports anyway.
- **Gates come from the target repo.** Prompts never name a gate command; they
  read `## Verification gates` from the repo's AGENTS.md or CLAUDE.md.
- **The verifier is in the YAML, not the prompt.** Model and provider live in
  the `agent:` block. A claude verifier gets no `allowed_tools`, because it
  must run the gates.
- **`timeout_seconds` is the agent's work budget.** Provisioning is outside it
  (`SYN_SETUP_PHASE_TIMEOUT_SECONDS`). Running gates, pushes and `gh` calls are
  inside it.
- **Name the trap in the prompt.** Each prompt names the prior failure it must
  not repeat and the command that proves it did not.
- **Skills are invoked by name.** Agents use skills only when the prompt names
  them, so a phase that needs one names it.

## Before the PR

- `just check-workflows` (phase references, hardcoded gates).
- The workflow's own tests under `scripts/tests/` (for example
  `test_reverify_pr_workflow.py` keeps copied prompts identical).
- `syn workflow validate <dir>`.
- A live run on the VPS for anything that changes what a workspace receives.
  CI cannot see image or setup-env behaviour, and a green pin bump once broke
  every run.

## Shared prompts

`reverify-pr` copies implement-v3's verify, fix and finalize prompts because
`prompt_file` cannot reach outside its directory. Change one and you must
copy it to the other; the test enforces it.
