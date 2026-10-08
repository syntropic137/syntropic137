# implementer-seed-v1: the IMPLEMENTER eval kind (#1725)

The verifier suite (`evals/verifier-seed-v1`) asks whether a verifier BLOCKS a
known bug. This suite asks the other question: **given the problem, does the
implementing agent fix it?** It is scored by tests, not by reading a report.

## What a case is

| Field | Meaning |
|---|---|
| `commit` | The first parent of a real merged fix: the tree with the bug and none of the fix |
| `fix_commit` | The merge that shipped the fix |
| `task` | The problem as its issue (or the fix PR's symptom section) stated it, with the fix's own description of the solution removed. It must not name `source_pr`; `check` refuses one that does |
| `hidden_tests` | The pytest files the fix PR added or changed, run at their `fix_commit` content. They are not at `commit`, so the agent never sees them |

Where a hidden test imports a name the fix introduced, the task says so under
"Interface the scoring tests use". Without it no correct fix could pass except
by guessing a name, and the case would measure the guess. That paragraph
states the contract, not the implementation.

## Admission

A case is admitted only if its hidden tests discriminate:

```
uv run python scripts/eval_implementer.py check            # git only: SHAs, first parent, hidden files at the fix
uv run python scripts/eval_implementer.py admit [--case ID] # runs the tests: minutes per case
```

`admit` scores the empty patch (must be FAIL) and the fix's own diff minus
its hidden tests (must be PASS). The five cases were chosen from fix merges on
`main` since 2026-09-15 whose tests are self-contained unit tests (no
Postgres, no Docker, no pnpm). The `admit` output for this version is recorded
in the PR that added the suite.

## Running a case

1. **Implement**: launch `eval-implement-pinned-v1` (one `implement` phase,
   Opus, `delivers_repo_changes: false`) on an eval whose Baseline pins the
   case's `commit`, with the case's `task` as the `task` input. The phase
   writes `artifacts/output/implement.patch` and pushes nothing.
2. **Score**, in a workspace and never on the API host, because it runs the
   agent's code:

   ```
   uv run python scripts/eval_implementer.py score --case <id> --patch implement.patch
   ```

   It creates a throwaway worktree at the pin and checks out the submodules
   from the local clones, never from the network. It runs `uv sync` before the
   patch is applied, so a sync failure can only be the environment's. Then it
   applies the patch, writes each hidden test file at its `fix_commit` content
   (over whatever the patch did to that path) and runs pytest on those files
   and nothing else.

   | Result | Exit | When |
   |---|---|---|
   | PASS | 0 | every hidden test passed |
   | FAIL | 1 | the patch does not apply, a hidden test failed, or a hidden test could not be collected (the change does not provide what it imports) |
   | ERROR | 2 | the environment: the pin, a submodule commit or a hidden file is missing, `uv sync` failed, pytest erred internally or collected nothing, or the run timed out |

`launch` and the score ledger are not wired into `scripts/eval_suite.py` for
this kind yet. That script's `Case`, scoring and `_report_of` all assume a
verifier report. Today the run is launched like any eval run, and `score` is
run by hand inside a workspace with the patch copied into it. What is missing
for this to be automatic:

- **Patch handoff between executions.** No mechanism gives one execution's
  output artifact to a different execution's workspace as an input artifact.
  So the scorer cannot yet be a workflow of its own that consumes the
  implement run's patch.
- **`patch` is a name, not a type.** `output_artifacts` is a free list of
  strings. The platform collects whatever is under `artifacts/output/`, and
  nothing checks that `implement.patch` is there or that it is a diff.

## Leakage: NOT prevented today

The task requires that the workspace cannot fetch commits after the pin or
read the fix PR. **The platform cannot guarantee that today.** The suite
relies on the phase prompt's rules, which an agent can break:

| Channel | Why it is open | What closing it needs |
|---|---|---|
| Local object store | The provisioning clone is a full `git clone` of the default branch (`setup_phase_secrets.py`). The pin is a `checkout --detach` on top of it (`pinned_checkout.py`), so `git log --all` or `git show <fix>` already reach the fix, offline | A pinned-clone mode: `git init` + `git fetch --depth=1 origin <sha>` (or a bundle made at the pin), with no other refs and no remote-tracking branches |
| Remote fetch | Setup writes a GitHub credential to `~/.git-credentials` and logs in `gh` (#725), so `git fetch` and `gh pr view` work | A phase-level "no repo credential" option for read-only phases. An eval phase that writes a patch needs no credential after the clone |
| Network | The Envoy sidecar's egress allowlist works per host. github.com has to be allowed for the clone, so it cannot block "commits after X" | Clone during setup, then drop github.com from the allowlist for the agent's phase (or give the phase an empty allowlist) |

Until all three exist, a PASS means "the hidden tests passed on the agent's
patch". It does not prove the agent never saw the fix. Read the run's tool
trace (Bash commands that name `git log --all`, `git show`, `fetch`, `gh`)
before trusting an unexpectedly good score. Tracked as a follow-up on #1725.
