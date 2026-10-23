# E4: end-to-end replay eval, pilot (preregistered 2026-10-20)

Status: PREREGISTERED, not dispatched. Blocked on the replay target (see
Open decision). Owner GO 2026-10-20 ~20:40Z, cap 2 platform runs.

## Question

Does the full SDLC workflow, started from a pinned commit and a real issue,
produce a change that passes the real fix's held-out tests? What does that
cost, in time and in rounds? This is the end-to-end form the owner asked for:
one-phase evals (E1-E3) are only screening.

This pilot has n=1 per arm. It proves that the harness works and gives a first
reading. It cannot decide model choice on its own.

## Design

- **Seed:** issue #1420. The real fix is PR #2034, merge 90ad3abd9.
  - Pin = its first parent, c8397cffb5fe1b93783be467c28db16e56dc7981.
  - The real fix branch head is e527677ae16679298d355819c69239fac6efae9a.
- **Held-out tests:** the agent never sees these. They are the test files the
  real fix added or changed, under `packages/syn-domain/src/syn_domain/contexts/`:
  - `agent_sessions/slices/session_cost/test_unreported_cost.py`
  - `agent_sessions/slices/session_cost/test_calculate_many.py`
  - `agent_sessions/slices/session_cost/test_query_service.py`
  - `orchestration/slices/execution_cost/test_summary_path_multi_model.py`
  - `orchestration/slices/execution_cost/test_unreported_settlement_pool.py`
  - `orchestration/slices/execution_cost/test_unreported_summary_parity.py`
  - `tests/integration/test_observed_model_attribution_sql.py` is excluded: it
    needs Docker.
- **Validity check (before any dispatch):**
  - At the pin, the held-out set must have at least one failing test.
  - At the real fix, every test in it must pass.
  - Every test that fails at the pin is a target test.
  - If a test fails at the pin for an import or name reason, it is graded
    behaviorally. The grader maps names only where the run kept the same
    behavior under another name, and records each mapping.
- **Arms:** the workflow is `sdlc-implement-v4-precheck` verbatim, except for
  the implement and verify agents.

  | Run | Arm | implement | verify / reverify | When |
  |---|---|---|---|---|
  | R1 | swap | codex gpt-6.1-sol | claude-opus-5-5 | first, once the replay repo exists |
  | R2 | prod | claude-opus-5-5 | codex gpt-6.1-sol | after R1 is graded |

  Cross-family verification holds in both arms. R2's workflow is the installed
  production one. Before R1, R1's variant is diffed against it: only the
  implement and verify agent lines may differ.
- **Brief:** issue #1420's title and body as they were at the pin, plus one
  line, "Fix issue #1420." Nothing from the fix PR goes in.

## Validity check result (2026-10-20, local, no Docker)

The trees came from `git archive` of the pin and of the fix head. The
submodule pins are identical at both. Tests ran with
`uv run --frozen pytest -q`.

- **Fix head:** all 6 held-out files pass, 57 tests.
- **Pin, behavioral tier:** three files import cleanly at the pin:
  `test_calculate_many.py`, `test_query_service.py` and
  `test_summary_path_multi_model.py`. They hold 30 tests: **7 fail** and 23
  pass. At the fix, all 30 pass.
  - The 7 failures are the **target tests**.
  - The 23 that pass are the **guard tests** (regression check).
  - Every failure is a behavioral assertion, for example:
    - an execution total of 93.33 where 3.33 was expected;
    - an unreported summary repriced instead of costed from its turns.
- **Pin, API-coupled tier:** the other three files fail at collection.
  - `test_unreported_cost.py`, `test_unreported_settlement_pool.py` and
    `test_unreported_summary_parity.py` import names that only the real fix
    created, such as `zero_usage_group_by`.
  - They are **diagnostic only**: run them through recorded name mappings, and
    never count them in the primary outcome. A correct fix under other names
    must not lose to the real one.

The **primary outcome** is therefore: target tests passing (out of 7) and
guard tests failing (out of 23), both at the run's final head.

## Outcomes

| Measure | Source |
|---|---|
| Primary: target tests passing at the run's final head | held-out tests applied to a `git archive` of the head, `uv run pytest -q` |
| Held-out regressions (passed at the pin, fail at the head) | same run |
| Escaped defects | independent reverify (mandatory, `sdlc-reverify-pr-v1`) plus the grader's diff review against the real fix |
| In-run verify verdicts, rounds to certify | `/executions/{id}` phases and artifacts |
| Cost, wall time, per phase | `/executions/{id}` |

E3 run 07 implemented this same issue live on main: control arm, 2 rounds, fix
$5.53, 244 min, B1 found by verify. That is a reference point, not a control:
its base was not the pin.

## Decision rule (pilot)

- **Harness valid:**
  - the validity check passes;
  - both runs reach a final head;
  - the grader can apply the held-out tests to each head without hand edits
    beyond the recorded name mappings.
  - If any of these fails, fix the harness before any comparative run.
- **Signal for a follow-up:** we only call the follow-up comparison worth
  funding if an arm fails to pass every target test or has a held-out
  regression. Two passing arms with equal results say nothing about the
  models. They only show that this seed is easy.
- **No model decision comes from E4 alone.** A comparative E5 needs n >= 6
  seeds per arm, drawn from the escaped-bug seeds and merged fixes with unit
  tests.

## Constraints

- Before each dispatch:
  - message syntropic137-62 and post the exec id;
  - tag the run `eval-research` and `experiment:e4-replay`;
  - check that the platform total is at most 2.
- Quota (owner, 2026-10-20): the week runs on 3 Claude accounts via cswap,
  about 2 days each, and the owner swaps an account at 3% left. A single
  account being low is not a reason to hold. The run cap of 2 stands.
- Replay PRs are never merged. They are closed after grading.

## Open decision

v4-precheck is coupled to the default branch:
- premise reads `origin/main`;
- implement runs `git merge origin/main` first;
- verify, fix and reverify each start from a fresh clone of the default branch.

On syntropic137, a replay would merge the real fix into the agent's branch.
Premise would also refuse the task as already fixed. A pin written into the
brief cannot override the phase prompts (see the E2 "inputs-as-prompt-text"
trap).

The choice is with the orchestrator and the owner:

- **A (recommended):** a dedicated replay repository whose default branch is
  reset to the pin for each seed. The production workflow runs unchanged, and
  no PR lands on syntropic137.
- **B:** a variant workflow whose prompts swap `origin/main` for a per-seed base
  branch. It tests a modified workflow, and its PRs open on syntropic137.
