# The orchestrator tick

One pass, normally every 30 minutes. The order matters: verify before you
dispatch, and land before you dispatch more.

## 1. Read the state

- The scratchpad, `/Users/neural/Code/Syntropic137/dogfood-scratchpad.md`: the
  last log lines, the Queue and HUMAN REVIEW.
- Executions in flight, with phase and error:
  `syn137-api GET '/executions?page_size=20'`, then
  `syn137-api GET /executions/<id>` and read `.phases[].status` and `.error`.
- Open PRs: `gh pr list`. Ignore drafts that belong to other sessions.
- Main CI: `gh run list --branch main --workflow CI --limit 3`. Main red comes
  first, because every open PR inherits it.

## 2. Classify each run that ended

| Stored error | Meaning | Action |
|---|---|---|
| `REPORTED FAILURE` with a refusal or gap | the agent was right to stop | read its report; a platform gap becomes an issue and a run |
| `at capacity` | vendor blip | resume with `--acknowledge-external-effects` |
| `usage limit` / `try again at <date>` | vendor quota | page the owner (the watcher does this); no retry helps |
| `exit_code=124` | phase deadline | read the phase report; resume or split the task |
| `exit_code=137` | killed, usually OOM at the workspace cap | check `dmesg` on the host; size the limit |
| `finalize_pr` timeout after the PR is ready | the run did its job | review the PR normally |

## 3. Land what is ready

For each non-draft agent PR:

1. Worktree at the exact head: fetch `pull/N/head` into a named ref, assert the
   SHA, `git submodule update --init --recursive`, then merge `origin/main` in.
2. Second verifier: Codex `sdlc-reverify-pr-v1` or a local verifier subagent with
   the brief, the traps and mutation checks.
3. Run the targeted tests, plus `-m integration` locally, then
   `uv run pytest ci/fitness -q` and `just preflight`.
4. CI: every required check green and none cancelled. "CI Success" passes on
   cancelled jobs (#1623). The Vercel preview is not required.
5. `gh pr merge N --merge --match-head-commit <sha>`.
6. After merging one of two sibling PRs, merge main into the other and re-test
   it.

## 4. Deploy when there is something to deploy

- Run `just pit-stop 0.33.2-beta.N` only when main is green, on the commit you
  mean to ship. It drains, so in-flight runs delay it; that is fine.
- Read the result line. If the probe failed, find out why before anything else.
  An archived probe workflow is not a regression; a dropped start is a P0.
- After the swap, reinstall any workflows whose YAML changed, using the CLI built
  from main, and check the phase count on the server.

## 5. Refill

- Only if open agent PRs number 8 or fewer. Fill to 3-4 runs.
- At least 20% of dispatches go to tech debt and UI feedback. UI items come from
  `syn137-api GET '/feedback?status=open'`, and each item carries its selector
  and viewport.
- Write the prompt to `scratchpad/tasks/<slug>.md`, naming the trap and the
  command that proves it was avoided. Then dispatch with
  `syn137 workflow run sdlc-implement-v3 -t "$(cat …)" -R syntropic137/syntropic137`
  and read the `Execution ID:` line, not the first `exec-` match.

## 6. Record

- Add a scratchpad log line: what moved, what was merged (with the SHA), what was
  dispatched (with the execution id).
- Add a paper cut for every friction point: `PC-n`, the date, what happened, the
  execution or PR id, and the proposed fix.
- Extend the OKR lease (`okr checkout okrs-51p.23 … --ttl 4h`).
- Report to the owner in a few lines: merged, running, blocked, what needs them.
