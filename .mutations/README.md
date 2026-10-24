# Mutation evidence for #1389 (one home per release number)

Every patch is a unified diff against the fixed code. Node ids for
`just mutation-evidence`:

    apps/syn-api/tests/test_ui_feedback_build_identity.py
    ci/fitness/code_quality/test_no_hardcoded_version_literals.py

| patch | bug it re-introduces | killing test |
|---|---|---|
| 01-fastapi-version-back-to-a-literal | `FastAPI(version="0.1.0")` in ui_feedback/main.py | test_no_hardcoded_version_literals.py::TestNoHardcodedVersionLiterals::test_no_release_number_is_written_into_source, test_unreadable_metadata_reports_unknown_not_a_plausible_release[*] |
| 02-root-payload-reports-a-stale-literal | `GET /` reports a literal instead of the app's version | test_root_payload_version_is_the_installed_distribution, test_unreadable_metadata_reports_unknown_not_a_plausible_release[*] |
| 03-only-package-not-found-is-caught | metadata read catches only `PackageNotFoundError` | test_unreadable_metadata_reports_unknown_not_a_plausible_release[PermissionError], [MessageError] |
| 04-unreadable-metadata-invents-a-release | unreadable metadata falls back to "0.1.0" | test_unreadable_metadata_reports_unknown_not_a_plausible_release[*] |
| 05-literal-dunder-restored | `ui_feedback.__version__ = "0.1.0"` comes back | test_package_carries_no_second_version_home, test_no_release_number_is_written_into_source |
| 06-scan-skips-submodules | the scan drops `--recurse-submodules` | TestNoHardcodedVersionLiterals::test_exceptions_are_submodule_only_explained_and_not_stale (needs submodules checked out) |
| 07-annotated-dunder-not-detected | `__version__: str = "1"` escapes the check | test_planted_literal_is_caught[annotated dunder] |
| 08-fastapi-subclass-not-detected | a `*FastAPI` subclass call escapes the check | test_planted_literal_is_caught[FastAPI subclass] |

Each was applied and run locally; each failed the named tests, and the tree
reverted clean. The trusted run is `mutation-evidence.yml`, not this note.
