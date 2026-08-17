# 2026-08-17 Green checks that check nothing

## What happened

While validating an unrelated pricing change, a local test run surfaced two
tests failing on `main`. They had been red since #816 six days earlier, through
a full green CI on every PR in between.

Pulling that thread found four separate gates in this repo that report success
while verifying nothing. Not four bugs - one bug, four times.

## Timeline

- 16:24 - Validating cost attribution, ran the full local suite rather than `just test-unit`
- 16:31 - Two failures in `test_cost_model_resolution.py`: `assert Decimal('35.00') == Decimal('75.0')`
- 16:33 - Confirmed they fail on a clean `main` with my changes stashed. Not mine, and not new
- 16:35 - Cause: the file has no `@pytest.mark.unit`, and CI runs `pytest -m unit`
- 16:38 - Census: 3001 tests total, 1523 marked `unit`, 178 `integration` (CI reports SKIPPED), **1359 marked with nothing and run by no job**
- 16:45 - Ran all 1359. Only those 2 fail, so the damage was contained
- 16:52 - Full unit run surfaced two `XFAIL` lines: `test_no_orphaned_on_handlers` and `test_all_handler_methods_exist_on_projections`, both `xfail(strict=True)` against TODO(#444)
- 16:55 - Those are the exact guards that would have caught the `SkillRegistered` routing gap found earlier the same day (#821). The check existed, detected the problem, and was marked expected-to-fail

## Root cause

**Absence of verification is indistinguishable from successful verification.**

Every instance produces the same observable outcome - a green check, or silence -
whether the gate ran and passed, or never ran at all:

| Gate | What it claimed | What it did | Signal |
|---|---|---|---|
| VSA CLI pin | running 0.12.0 | ran 0.6.1-beta for months; loose `restore-keys` plus `if ! command -v vsa` (presence, not version) | green |
| `EVENT_HANDLERS` | events routed to projections | `SkillRegistered` absent; `dispatch_to_handlers` logged and dropped it | green, one log line |
| `pytest -m unit` | the suite ran | 1359 tests selected by no job | green |
| `xfail(strict=True)` | known issue tracked | two correctness invariants disarmed | green (XFAIL) |

Each individually looks reasonable. A marker-based selector is normal. An
`xfail` with an issue reference looks diligent. A cache with `restore-keys` is
idiomatic. The failure is that **none of them emits a number anyone checks.**

The deeper pattern: our gates answer "did anything fail?" when they should
answer "how much did you verify, and was that the expected amount?" The first
question cannot distinguish an empty run from a passing one. The second can.

## What we changed

- `16535fa2` - fixed the two stale-rate tests ($35.00 for 1M in + 1M out after
  #816 corrected gpt-5.6 to $5/$30), added the missing `unit` marker, and put
  the reason in the module docstring so the next author does not repeat it
- `16535fa2` - `test_model_alias_coverage.py`: every `ModelAlias` must map to a
  `ModelId`, resolve to a real rate, and carry positive prices. Mutation-verified
- `.github/actions/setup-vsa/action.yml` (earlier) - cache key now carries the
  exact version and submodule SHA, no `restore-keys`, installs with `--force` on
  mismatch, and **fails the job** if PATH still disagrees. CI now prints
  `Pinned VSA version: 0.12.0 (submodule 335075a4...)`
- #825 - the 45% CI coverage gap
- #821 (comment) - the disarmed guards, with the recommendation to fix and
  un-`xfail` the two existing tests rather than write a third

## The principle worth keeping

**A gate must publish a census, and something must assert the census.**

Not "did it fail" but "how many did it check". We already have exactly the right
mechanism in this repo and simply have not pointed it at coverage: the
untyped-dict ratchet in `justfile:check-untyped-dicts` reads a threshold from
`fitness-exceptions.toml`, prints the count, and fails when the count exceeds it.
A number that can only move one way.

The same shape applies to every gate above:

- **tests** - assert `unit + integration + e2e == total collected`; any
  unmarked test fails the build with its name. Coverage becomes opt-out
  (fail-closed) rather than opt-in (fail-open)
- **skips and xfails** - counted and budgeted like untyped dicts, ratcheting to
  zero. An `xfail` on a correctness invariant is a **disabled alarm, not a
  known issue**; if it must exist, it must be visible and shrinking
- **pinned tools** - assert the version the job *printed*, never that the
  install step went green
- **event routing** - the guard already exists; arm it

## Open follow-ups

- [ ] #825 - add the collection census to CI; make unmarked tests fail
- [ ] #825 - un-skip the 178 integration tests, or make the skip reason explicit
      and deliberate. A green check that proves nothing is worse than a red one
- [ ] #821 / #444 - fix the 6 dangling `EVENT_HANDLERS` entries and 5 orphaned
      handlers, then delete both `xfail` markers
- [ ] Add a skip/xfail budget to `fitness-exceptions.toml` alongside untyped-dicts
- [ ] Consider a meta-test per CI gate: a known-bad fixture proving the gate
      goes red. A gate that has never been observed failing is unverified
