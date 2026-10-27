Mutation evidence for #2107 newest-only capture discovery. Each patch is killed by
`packages/syn-adapters/tests/test_session_inventory_postgres.py::test_capture_delivery_queues_only_the_newest_revision_per_run_transcript`.

- 01-queue-every-revision: the old behaviour; every catalogued revision is queued.
- 02-newest-by-catalogue-time: picks the most recently catalogued row instead of the largest revision.
- 03-withdrawn-newest-falls-back-to-older: applies the deletion filter before picking, so an older revision replaces a withdrawn newest one.
