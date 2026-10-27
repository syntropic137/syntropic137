# #2119 mutation evidence

Tests: `packages/syn-adapters/tests/test_session_archive_splice.py` and
`apps/syn-api/tests/test_2107_session_archive_dedupe.py`. Local sweep: 16/16 killed.

| Patch | Bug | Killed by |
|---|---|---|
| 01-read-skips-reverify | read assembles the slice without verifying it | test_deleting_a_base_with_a_damaged_referrer_fails_without_losing_it |
| 02-reconstruct-skips-hash | verification checks size only | test_reconstruct_rejects_any_damaged_field |
| 03-unlink-before-reference-commit | full object unlinked before the reference commits | test_reference_commits_before_the_full_object_is_unlinked |
| 04-skip-retargets | referrers of a spliced base are not moved | test_splicing_a_base_retargets_its_referrers_first |
| 05-delete-skips-materialize | deleting a base strands its referrers | test_deleting_a_base_turns_its_referrers_back_into_full_objects |
| 06-delete-keeps-pin | deleting a referrer leaves its pin | test_deleting_a_referrer_removes_its_reference_and_pin |
| 07-reference-as-base | a reference (with a crash-left full copy) becomes a base | test_a_reference_whose_full_object_a_crash_left_is_never_a_base |
| 08-lock-stripe-twice | one stripe taken twice self-deadlocks | test_two_digests_on_one_lock_stripe_do_not_deadlock |
| 09-no-saving-guard-dropped | reference written when no smaller | test_a_reference_larger_than_the_object_is_not_written |
| 10-read-holds-whole-base | slice read inflates the whole base | test_reading_a_slice_keeps_only_the_slice_of_its_base |
| 11-reference-temporaries-not-reclaimed | killed reference writer leaks temporaries | test_a_killed_reference_writer_leaves_nothing_behind |
| 12-short-gzip-magic-seeks-trailer | short magic-prefixed body aborts summary | test_a_short_body_starting_with_the_gzip_magic_is_summarised |
| 13-reference-fields-unchecked | damaged length read before validation | test_a_damaged_slice_length_is_refused_before_the_base_is_read |
| 14-receipt-size-unchecked | self-consistent enlargement read before refusal | test_a_damaged_slice_length_is_refused_before_the_base_is_read |
| 15-reference-read-unbounded | reference file read whole | test_a_reference_file_is_read_with_a_bound |
| 16-oversized-reference-written | reference over MAX_REFERENCE_BYTES written | test_a_reference_over_the_bound_is_never_written |
