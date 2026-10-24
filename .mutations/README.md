# Mutation evidence for #2100 (dead warnings plumbing; can_open_pr reaches the server)

Every patch is a unified diff against the fixed code. Node id for
`just mutation-evidence` (pytest only; patches 01-03 are TypeScript and are
killed by vitest locally, see below):

    apps/syn-api/tests/test_endpoint_workflows_from_yaml.py

| patch | bug it re-introduces | killing test |
|---|---|---|
| 01-single-file-strips-retired-key | `syn workflow validate <file>` drops `can_open_pr` before upload, so the server never sees it | apps/syn-cli-node/tests/commands/workflow/crud.test.ts > a retired phase key > a single file reaches the server unchanged, prints the refusal and exits non-zero |
| 02-package-strips-retired-key | package validation normalizes the key away in JSON.stringify | crud.test.ts > a retired phase key > a package directory keeps the key, prints the refusal and exits non-zero |
| 03-invalid-single-file-exits-zero | an invalid single file prints the refusal but exits 0 | crud.test.ts > a retired phase key > a single file reaches the server unchanged, prints the refusal and exits non-zero |
| 04-install-reports-a-phantom-warning | the from-yaml response invents a notice after the internal plumbing was removed | apps/syn-api/tests/test_endpoint_workflows_from_yaml.py::test_install_without_a_retired_key_has_no_warnings |

Each was applied and run locally (`pnpm -C apps/syn-cli-node exec vitest run
tests/commands/workflow/crud.test.ts`, `uv run pytest -m unit -q <file>`); each
failed the named test, and the tree reverted clean.
