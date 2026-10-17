# Mutation evidence for PR #2013 (feedback plan PR 2, #2010)

Each patch re-introduces one bug from the plan's section 3 negative controls. The
listed node ids must fail with the patch applied. Delete this directory before merge.

PR #2011 (plan PR 1) has merged to main. Its patches 01-03 were run by the hosted
runner (run 39017304744, all killed) and removed in bf071e9d4 before that merge, so
this directory holds only PR 2's patch, and the command below covers every patch here.

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

Checked locally before pushing: with the patch applied, exactly those three ids
failed and every other test in the file passed. With it reverted, all passed.
