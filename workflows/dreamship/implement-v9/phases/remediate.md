---
model: opus
timeout-seconds: 3600
---

# Address the review

$ARGUMENTS

## Skills for this phase (load them first)

Load each skill below with the Skill tool before you change anything, and apply it while you work. Your first output line must be `SKILLS LOADED:`, followed by the names you loaded. Name any skill you could not load, with the reason.

- `software-leverage-review`
- `testing`
- `security`
- `architecture`
- `managing-beads`
- `delivery-process`
- `merging-a-pr`
- `red-gates-and-fitness`

The following are also installed, for `software-leverage-review`'s per-point reviewers. You do not need to load them yourself:

- `boundary-hardening`
- `ci-optimization`
- `configuration`
- `continuous-delivery`
- `dependencies`
- `developer-experience`
- `documentation`
- `dry`
- `environments`
- `error-handling`
- `extensibility`
- `logging`
- `principles-and-patterns`
- `purpose-and-scope`
- `software-complexity`
- `types`
- `versioning`

## Run software-leverage-review in this session (required)

Run it on your own fixes before you push them. Fix every headline (auto-fix) finding it raises about your fixes.

Run it here, as its orchestrator:
- **Do not use `claude -p`.** It is not logged in inside this workspace. The skill asks for `claude -p` only so that its orchestrator is a top-level session able to dispatch subagents. You already are one.
- **Follow its Workflow, steps 1 to 8, yourself.**
  - TARGET: `git -C <repo> diff <the head you started from>..HEAD > /workspace/artifacts/output/slr-remediate/diff.patch` once your fixes are committed.
  - OUTPUT_DIR: `/workspace/artifacts/output/slr-remediate`. Files under `/workspace/artifacts/output/` are kept after this phase ends.
  - Dispatch one reviewer per leverage point in its `slp-manifest.yaml` with the Agent tool, in parallel, each with `prompt_review-one-software-leverage-point.md`. Every point's skill is installed here.
  - **Each reviewer must load its own point's skill.** Append this to every dispatch prompt, word for word:

    > Before you read the diff, invoke the Skill tool for your software leverage point. Do not review without it. End your one-line confirmation with ` | skill: <the "Base directory for this skill" the Skill tool printed> @ <commit>`. The commit is `9dad3b8fad04d1c5bfd4ccc01b69caf78bc7f613` for a directory under `/workspace/.claude/skills/`, or the output of `git -C <repo> rev-parse HEAD` for a directory inside a cloned repo.
  - **Check every confirmation before you dedup.**
    - If a reviewer's confirmation has no `skill:` part, or names a directory that is not that point's skill, re-dispatch that reviewer once, with the same prompt.
    - If any reviewer still has none, the review is incomplete. Post the report anyway with `INCOMPLETE` in its title, name each unloaded reviewer, end your output with `SLR INCOMPLETE: <points>`, and do not mark the PR ready.
  - **The report starts with a table:** every reviewer, the skill directory it loaded, and the commit.
  - Run its scripts with `uv run python`.
- **Post the rendered markdown report as a comment on the PR.** Print `SLR REPORT:` followed by the comment's URL and the report's path.
- **If any step cannot run,** name the step and the reason in your output and on the PR. A review you write by hand is not this skill, so do not call it one.

## Output

Write to `artifacts/output/deliverable.md`: each blocker and what you did about
it, the commands you ran with their results, the new commit SHA, and whether you
consider the PR ready to land. If it is not ready, say exactly what remains.
