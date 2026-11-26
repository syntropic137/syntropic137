# Mutation evidence for #1863 part 1 (PR #2375)

Tests: `scripts/tests/test_check_setup_template_current.py` (no Docker; run with `false`).

| Patch | Bug | Killed by |
|---|---|---|
| 01-header-not-compared | release header never compared | test_release_header_difference_is_a_mismatch |
| 02-digest-compare-ignores-found-side | digests read from the release side only | test_one_digest_difference_names_that_image, test_image_missing_from_the_setup_template_is_a_mismatch |
| 03-extra-setup-image-ignored | an image only in the setup template is ignored | test_image_only_in_the_setup_template_is_a_mismatch |
| 04-tag-dropped-from-pin | `name:tag@sha256:` loses its tag | test_tag_on_a_pinned_ref_is_compared |
| 05-requested-release-not-validated | a stale asset header certifies the requested release | test_requested_release_is_validated_against_asset_header |
| 06-malformed-pin-accepted | an overlong or malformed digest is truncated or skipped | test_digest_is_not_silently_truncated, test_malformed_pin_beside_a_valid_one_is_a_parse_error |
| 07-tarball-decode-error-escapes | a non-UTF-8 template escapes as a traceback, not exit 2 | test_bad_template_encoding_returns_exit_two |
| 08-brace-ends-quoted-ref | `}` ends a ref, so a quoted `@sha256:<64>}bad` is truncated and accepted | test_quoted_suffix_after_a_valid_pin_is_a_parse_error, test_main_rejects_a_quoted_suffix_in_the_setup_template |
| 09-pin-outside-scalar-counted | a pin in a trailing comment is counted without being validated | test_pin_in_a_trailing_comment_is_a_parse_error |

Dispatch: `just mutation-evidence 2375 "scripts/tests/test_check_setup_template_current.py" false`
