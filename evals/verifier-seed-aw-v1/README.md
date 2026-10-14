# verifier-seed-aw-v1: the verifier seed suite for agentic-workspace

The same eval as [verifier-seed-v1](../verifier-seed-v1/README.md), over
`AgentParadise/agentic-workspace` instead of syntropic137. An eval's baseline
pins one SHA per repository, so a second repository is a second suite.
Every rule is verifier-seed-v1's and lives in its README: how a defect case
is pinned, how a clean control is chosen, how a blocked run is judged, and
how a case is retired. This file holds only what differs.

## Checking it

`check` reads the pins from an agentic-workspace checkout, so name one:

```
git submodule update --init lib/agentic-workspace
git -C lib/agentic-workspace fetch origin
uv run python scripts/eval_suite.py check --suite evals/verifier-seed-aw-v1 --repo lib/agentic-workspace
```

Without `--repo`, `check` looks in syntropic137 and reports every pin as
missing.

## What differs

- **Clean controls come from imported history.** agentic-workspace's mainline
  before 2026-09-25 was imported from `AgentParadise/agentic-primitives`, and
  its own PR numbers restart there. A control merged before then has
  `source_pr` set to the agentic-primitives PR its merge names, by number
  or, for some imported merges (`0dfa63a`), by title only: list merges by
  parent count, not by "Merge pull request". Rule 2's search covers both
  repositories.
- **Non-Python expected files.** `scripted-agent-tests-not-in-ci` expects
  `.github/workflows/ci.yml`: the defect is a package the CI matrix omits,
  visible in the diff without running anything.
- **Imported pins have no CI files.** The import carried no `.github/` before
  2026-09-22 (`b00e963`), so a control pinned in imported history has no CI
  workflow at its pin, whatever agentic-primitives ran at the time. A
  verifier that asks which CI job runs a test will find none there. Score
  that block as it stands (a control blocked is a false block) and say in
  the write-up which findings rest only on the missing CI files.

## Rule 4: a control must have survived, not just waited (from v3)

verifier-seed-v1's rules 1-3 hold, and in this suite they were not enough.
Both arms of the checks-treatment A/B blocked all three v2 controls. Every
one of the six blocked reports was read in full and checked against its pin.
The platform's artifacts route was unreachable, so the reports were read from
the `verify.md` each run wrote, in its session transcript in the deployment's
session store (`GET $AGENTIC_SESSION_STORE_URL/v1/sessions/search?tags=execution_id:<id>`,
then `/v1/sessions/<session_id>`). None of the blocks was false. Each
control's every non-CI finding is shared by both arms:

- `clean-staged-teardown` (exec-ca359d2d2e15 control, exec-479751d1afef
  treatment). Both arms found three things: the `lock.locked()` waiter race
  (`providers/docker.py:715`), `_remove` discarding `docker rm`'s exit status
  (`:814`), and a second cancellation releasing the lock while the shielded
  removal is still running (`:755`). AW#56 fixed the first two seven weeks
  after the merge (`e241fdf`). It passed rule 3 because its functions were
  quiet for 30 days. Nothing touched them until somebody read them closely.
  It is reclassified as `teardown-lock-waiter-race`. The shield finding has
  no fix, so it is not expected.
- `clean-deployment-identity` (exec-5b26b73f76d9 control, exec-c1037513be15
  treatment). Both arms found that the probe at
  `tests/integration/test_entrypoint_capabilities.py:4003`
  (`${VAR:-unset}`) cannot tell an absent variable from an empty one. Its
  own task asked whether the tests prove exactly that. The finding is true
  and still unfixed on AW main, so the case is retired with no defect case.
- `clean-event-type-identifiers` (exec-c56d8e6252c9 control,
  exec-f21b0e538b82 treatment). Both arms found two things:
  - `plugins/observability/hooks/git/install.py:22`: `HOOKS` omits the
    `post-checkout` hook this PR adds (`795a270`), so neither documented
    install mode installs it. At the pin, `HOOKS` is `["post-commit",
    "post-merge", "post-rewrite", "pre-push"]` beside a `post-checkout`
    file. The list is unchanged on AW main (`2f12be8`).
  - `providers/claude_cli/event_parser.py:155`: `SessionOutputStream`
    dispatches on `type`. The hook envelopes the PR now merges into the
    Docker stream carry `event_type`, so they are dropped.

  The installer finding is a real defect, and it has no fix. The case is
  retired as a candidate defect, to be added once a fix exists.

The treatment's further findings (absent CI, at all three pins; test
adequacy, at event-type) sit beside these shared ones. None of its blocks
rests on check 2 alone.

Thirty quiet days means nobody changed the code. In a repository that moves
this fast, it does not mean anybody read it again. So from v3, a control must
also meet this rule:

4. **Its code survived to `clean_through`, re-read and its tests biting.**
   - a. No mainline commit between the merge and `clean_through` changes a
     Python function the PR changed. This is rule 3 with the window extended
     from 30 days to the whole of later history. `clean_through` is AW main
     when the version is cut.
   - b. At least 3 later mainline merges changed the same files and left
     those functions alone, so the code was in front of later reviews and
     survived them.
   - c. The PR changes product code, not only tests, docs or version pins.
     Its tests pass at the pin, and at least one of them fails when the PR's
     product change is reverted at the pin (a revert mutation). The commands
     and the failing test are recorded in the case file.
   - d. Its `task` does not ask whether a property is proven, unless the
     selector has checked that the pin's tests prove it. A control whose task
     invites a true test-adequacy finding is not a control.

4a can be checked mechanically with `eval_suite`'s own `_touched(repo,
merge, clean_through)`. `check` does not run it yet: `check` is shared with
verifier-seed-v1, and widening rule 3 there is its own change. 4b, 4c and 4d
are applied by hand. 4c needs a test run, which a git-only `check` cannot do.

**v3 applied it, and no merge qualified.** Every mainline merge on AW main
(`37f210b`, 2026-10-13) at least 30 days old was read:

| Merge | Fails | Why |
|---|---|---|
| #359, #360 | 4c (and rule 3, by hand) | They pass 4a: no function changed through main. But their Python changes are tests or docstrings only, and their shell changes are rewritten within 30 days (`suite.yaml` v1/v2 notes) |
| #362 | rule 3, by hand | It passes 4a, and it has one product Python change with a test (`build-provider.py` copies with `symlinks=True`). But #363, #369, #382 and #387 change the omni-agent Dockerfile it touched within 30 days (`suite.yaml` v1 note). It is the nearest miss |
| #355 | rule 3 | `check`: #358 rewrites two of its functions |
| #345 | 4a | `fbb5cbb` and `0f48e8c` change `SecurityConfig.to_docker_run_args` |
| #346 | 4a | `119f465` changes `doctor._exporter_present` |
| #55 | 4a | `eb890d4` and `6757969` change 8 of its functions |
| #240 | - | A candidate defect (cancellation ordering), not a control (v2 note) |
| #87, #348, #358 | - | Retired in v3: blocked by both arms (`suite.yaml` v3 note) |
| the rest | 4c | No Python, or version-pin and release bookkeeping only |

So v3 has no clean controls, and it measures catch rate only. A false-block
guard needs a control that passes rule 4. The next candidates are the
September and October merges, once they reach 30 days and have 3 later
merges over their files. Re-run the 4a scan then, and a revert mutation on
whatever survives.
