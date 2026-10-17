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
