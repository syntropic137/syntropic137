Mutation evidence for #2107 compression at rest. Each patch is killed by
`packages/syn-adapters/tests/test_session_transcript_archive.py` and
`apps/syn-api/tests/test_2107_session_archive_compress.py`.

- 01-written-uncompressed: new objects are not compressed.
- 02-trailing-bytes-accepted: a gzip stream followed by extra bytes reads as the body.
- 03-dry-run-rewrites: the dry run rewrites objects.
- 04-deleted-object-rewritten: a tombstoned object is re-encoded instead of skipped.

Not included: removing either layer of the two-layer verify in compress_in_place
survives, because the other layer alone refuses a corrupt object. That redundancy
is intended.
