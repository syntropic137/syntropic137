# Mutation evidence for PR #2011 (feedback plan PR 1, #2010)

Each patch re-introduces one bug from the plan's section 3 negative controls. The
listed node ids must fail with the patch applied. Delete this directory before merge.

| Patch | Bug it re-introduces | Node ids that must fail |
|---|---|---|
| `01-drop-membership-check.patch` | `AddReport` no longer checks membership, so the same submission is reported twice | `packages/syn-domain/src/syn_domain/contexts/feedback/test_ticket.py::TestMembership::test_the_same_report_twice_counts_once` |
| `02-resolution-any-source.patch` | `ResolutionPolicy` resolves when ANY signed reporter observed the fix | `packages/syn-domain/src/syn_domain/contexts/feedback/test_ticket.py::TestResolution::test_one_of_two_signed_sources_does_not_resolve` `packages/syn-domain/src/syn_domain/contexts/feedback/domain/test_pure_policies.py::TestResolutionPolicy::test_every_signed_reporter_must_have_observed_the_fix` |
| `03-delete-feedback-vocabulary.patch` | the feedback vocabulary file is deleted | `ci/fitness/code_quality/test_ubiquitous_language.py::test_every_context_has_a_vocabulary[feedback]` |

None of these needs Docker:

```
just mutation-evidence 2011 "packages/syn-domain/src/syn_domain/contexts/feedback/test_ticket.py::TestMembership::test_the_same_report_twice_counts_once packages/syn-domain/src/syn_domain/contexts/feedback/test_ticket.py::TestResolution::test_one_of_two_signed_sources_does_not_resolve packages/syn-domain/src/syn_domain/contexts/feedback/domain/test_pure_policies.py::TestResolutionPolicy::test_every_signed_reporter_must_have_observed_the_fix ci/fitness/code_quality/test_ubiquitous_language.py::test_every_context_has_a_vocabulary[feedback]" false
```

Checked locally before pushing: each patch applied, its node ids failed, and they
passed again once it was reverted. Patch 01 first SURVIVED against an assertion on
the aggregate's own member count, which a replayed duplicate cannot raise. The test
now also folds the count from the event stream, as a read model does.

## PR #2013 (feedback plan PR 2, stacked on #2011)

| Patch | Bug it re-introduces | Node ids that must fail |
|---|---|---|
| `04-drop-timestamp-from-canonical-string.patch` | the canonical string no longer covers `X-Syn-Timestamp`, so a captured request can be re-dated | `packages/syn-domain/src/syn_domain/contexts/feedback/test_source_signing.py::TestCanonicalSignature::test_a_tampered_timestamp_inside_the_window_fails` `packages/syn-domain/src/syn_domain/contexts/feedback/test_source_signing.py::TestCanonicalSignature::test_the_fixed_vector_verifies` `packages/syn-domain/src/syn_domain/contexts/feedback/test_source_signing.py::TestCanonicalSignature::test_the_fixed_vector_is_what_the_signer_produces` |

The first id is the plan's negative control. The ±301 s tests do NOT catch this
bug: they sign honestly at the skewed time, so the window check refuses them
whatever the canonical string holds. Only a re-dated request with the original
signature can tell, and it is re-dated by 60 s so the window cannot be what
refuses it. No Docker needed:

```
just mutation-evidence 2013 "packages/syn-domain/src/syn_domain/contexts/feedback/test_source_signing.py::TestCanonicalSignature::test_a_tampered_timestamp_inside_the_window_fails packages/syn-domain/src/syn_domain/contexts/feedback/test_source_signing.py::TestCanonicalSignature::test_the_fixed_vector_verifies packages/syn-domain/src/syn_domain/contexts/feedback/test_source_signing.py::TestCanonicalSignature::test_the_fixed_vector_is_what_the_signer_produces" false
```

Checked locally before pushing: with the patch applied, all three ids failed and
the other 23 tests in the file passed. With it reverted, all 26 passed.
