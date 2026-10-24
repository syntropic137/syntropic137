# Mutation evidence for #1389 (one home per release number)

Every patch is a unified diff against the fixed code; none mutates a test file.
Node ids for `just mutation-evidence`:

    apps/syn-api/tests/test_ui_feedback_build_identity.py
    ci/fitness/code_quality/test_no_hardcoded_version_literals.py
    scripts/tests/test_check_version_literals.py

| patch | bug it re-introduces | killing test |
|---|---|---|
| 01-fastapi-version-back-to-a-literal | `FastAPI(version="0.1.0")` in ui_feedback/main.py | test_no_hardcoded_version_literals.py::TestNoHardcodedVersionLiterals::test_no_release_number_is_written_into_source, test_unreadable_metadata_reports_unknown_not_a_plausible_release[*] |
| 02-root-payload-reports-a-stale-literal | `GET /` reports a literal instead of the app's version | test_root_payload_version_is_the_installed_distribution, test_unreadable_metadata_reports_unknown_not_a_plausible_release[*] |
| 03-only-package-not-found-is-caught | metadata read catches only `PackageNotFoundError` | test_unreadable_metadata_reports_unknown_not_a_plausible_release[PermissionError], [MessageError] |
| 04-unreadable-metadata-invents-a-release | unreadable metadata falls back to "0.1.0" | test_unreadable_metadata_reports_unknown_not_a_plausible_release[*] |
| 05-literal-dunder-restored | `ui_feedback.__version__ = "0.1.0"` comes back | test_package_carries_no_second_version_home, test_no_release_number_is_written_into_source |
| 06-scan-skips-submodules | the scan drops `--recurse-submodules` | TestNoHardcodedVersionLiterals::test_exceptions_are_submodule_only_explained_and_not_stale (needs submodules checked out) |
| 07-annotated-dunder-not-detected | `__version__: str = "1"` escapes | test_check_version_literals.py::test_planted_dunder_is_caught[annotated] |
| 08-fastapi-matched-by-spelling | callee matched by `endswith("FastAPI")` again | test_planted_fastapi_version_is_caught[from import as], [renamed], [rename chain], [annotated rename] |
| 09-import-alias-ignored | `from fastapi import FastAPI as API` not resolved | test_planted_fastapi_version_is_caught[from import as] |
| 10-renames-not-resolved | `API = FastAPI` (and chains) not resolved | test_planted_fastapi_version_is_caught[renamed], [rename chain] |
| 11-only-if-and-try-traversed | `with`/`for`/`while`/`match` bodies skipped | test_planted_dunder_is_caught[in with], [in for], [in for else], [in while], ... |
| 12-function-bodies-traversed | function/class bodies treated as module scope | test_clean_source_is_not_flagged[function-local dunder], [class attribute dunder], [dunder in method under if] |
| 13-deleted-file-not-stale | a file gone from a checked-out submodule keeps its exception | test_a_file_deleted_from_a_checked_out_submodule_is_stale |
| 14-module-alias-ignored | `import fastapi as f; f.FastAPI(...)` not resolved | test_planted_fastapi_version_is_caught[module alias] |

Each was applied and run locally; each failed the named tests, and the tree
reverted clean. The trusted run is `mutation-evidence.yml`, not this note.
