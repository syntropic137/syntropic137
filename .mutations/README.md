Mutation evidence for #2107 live re-sweep gate. Each patch is killed by
`packages/syn-adapters/tests/test_capture_spool_recovery.py::test_caught_up_live_spool_is_reswept_only_on_settlement_or_live_interval`.

- 01-no-live-gate: the old behaviour; every caught-up live spool is re-swept every retry.
- 02-settlement-not-claimed: a settled spool waits for the live interval.
- 03-envelope-traversal-gated: an unfinished transcript traversal waits for the live interval.
- 04-child-traversal-gated: an unfinished child-journal traversal waits for the live interval.
- 05-live-interval-never-elapses: a live spool is never re-swept.
