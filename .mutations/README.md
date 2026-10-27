# Mutation patches: #1917 slice 2

One patch per meaningful check, non-test files only. `killers.tsv` maps each to
the test that kills it. The PR runs them through `just mutation-evidence <pr> "<ids>"` (scripts/mutation_evidence.py); locally they were verified by a script that first
runs every killing test on clean HEAD (all must pass), then for each patch:
applies it, asserts the source changed, runs its test (must fail), reverts.

Docker: the `test_1917_outage_breaker_and_recovery_postgres.py` killers
(m01-m09, m19) are `integration` and need Postgres (test stack on 15432 or
testcontainers). m10-m14, m16-m18, m20 and m21 are `unit`, no docker.

| Patch | Check it removes |
|---|---|
| m01 | claim step 1 ignores the breaker |
| m02 | a breaker-disabled higher executor still holds lower pools back |
| m03 | breaker trips one failure late |
| m04 | a successful create does not re-enable claims |
| m05 | fence/takeover reach ignores held Recovery Kits |
| m06 | fence/takeover reach unguarded (any executor fences) |
| m07 | register drops recovery_scopes |
| m08 | FencedRun loses the claimer's scope |
| m09 | reconciler reaps with its own backend, not the kit |
| m10 | host accepts kits it did not declare (or the reverse) |
| m11 | E2B reaper skips the confirming listing |
| m12 | E2B reaper kills nothing |
| m13 | E2B create failures never reach the breaker |
| m14 | memory double: claim ignores the breaker |
| m16 | E2B executor's pool declares host credentials |
| m17 | local executor with SYN_E2B_RECOVERY_API_KEY holds no kit |
| m18 | production wiring bypasses the breaker client |
| m19 | after the cooldown every claim gets through, not one probe |
| m20 | memory double: same as m19 |
| m21 | the E2B executor starts outside test/offline on an unverified (label-listing) reap (#1916 guard) |

m15 (memory double: reach ignores kits) was dropped to stay within 20 patches: it mirrors m05, which the Postgres test kills.
