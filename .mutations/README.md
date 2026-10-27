Mutation evidence for #2107 live re-sweep gate. Each patch is killed by
`packages/syn-adapters/tests/test_capture_spool_recovery.py::test_live_spool_is_reswept_only_on_settlement_or_live_interval`.

- 01-no-live-gate: the old behaviour; every caught-up live spool is re-swept every retry.
- 02-settlement-not-claimed: a settled spool waits for the live interval.
- 03-never-traversed-gated: a spool never fully traversed is not claimable.
- 04-cooldown-from-claim-not-traversal: Codex pass 1 bug; a failed or abandoned traversal is throttled.
- 05-live-interval-never-elapses: a live spool is never re-swept.
