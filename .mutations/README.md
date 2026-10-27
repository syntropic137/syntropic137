Mutation evidence for #2107 compression at rest. Each patch is killed by
`packages/syn-adapters/tests/test_session_transcript_archive.py` and
`apps/syn-api/tests/test_2107_session_archive_compress.py`.

- 01-written-uncompressed: new objects are not compressed.
- 02-trailing-bytes-accepted: a gzip stream followed by extra bytes reads as the body.
- 03-dry-run-rewrites: the dry run rewrites objects.
- 04-deleted-object-rewritten: a tombstoned object is re-encoded instead of skipped.
- 05-gzip-magic-trusted: an object starting with the gzip magic is reported compressed unverified.
- 06-gzip-trailing-bytes-trusted: the migration accepts a gzip stream followed by extra bytes.
- 07-temporaries-not-reclaimed: a killed writer's temporary copy is never removed.
- 08-reclaim-other-digests: reclaiming one digest's temporaries removes another's.
- 09-delete-keeps-temporaries: deleting a body leaves its temporary copies behind.

Not included: dropping the check that the new encoding inflates back to the key
survives, because gzip round-trips by construction. It is a defence against a
broken encoder, not a reachable state.
