# Mutation evidence for #1863 part 1 (PR #2375)

Tests: `scripts/tests/test_check_setup_template_current.py` (no Docker; run with `false`).

| Patch | Bug | Killed by |
|---|---|---|
| 01-header-not-compared | release header never compared | test_release_header_difference_is_a_mismatch |
| 02-digest-compare-ignores-found-side | digests read from the release side only | test_one_digest_difference_names_that_image, test_image_missing_from_the_setup_template_is_a_mismatch |
| 03-extra-setup-image-ignored | an image only in the setup template is ignored | test_image_only_in_the_setup_template_is_a_mismatch |
| 04-tag-dropped-from-pin | `name:tag@sha256:` loses its tag | test_tag_on_a_pinned_ref_is_compared |

Dispatch: `just mutation-evidence 2375 "scripts/tests/test_check_setup_template_current.py" false`
