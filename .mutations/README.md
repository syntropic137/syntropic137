# Mutation evidence for #2130

Each patch is a mutation of non-test source on the PR head. The runner reads
only `*.patch`; this file maps each one to the tests meant to kill it. Delete
`.mutations/` after the evidence comment reports PASS for the head SHA.

Docker: `false`. No named test needs Docker; the fitness test reads the
Dockerfile as text and the install tests run the script against a `file://`
stub release.

| Patch | Mutates | Killed by |
|---|---|---|
| `01-run-shell-or-true.patch` | Dockerfile: exec-form RUN -> shell form `python -I ... \|\| true` | `ci/fitness/infrastructure/test_syn_api_exporter_pin.py::test_install_runs_the_tested_script_with_no_shell` |
| `02-run-shell-no-set-e.patch` | Dockerfile: exec-form RUN -> shell form `python -I ...; true` (no `set -e`) | `ci/fitness/infrastructure/test_syn_api_exporter_pin.py::test_install_runs_the_tested_script_with_no_shell` |
| `03-skip-checksum-compare.patch` | script: sha256 comparison disabled | `scripts/tests/test_install_apss_exporter.py::test_wrong_checksum_fails_and_installs_nothing`, `::test_other_arch_checksum_is_not_accepted` |
| `04-main-swallows-failure.patch` | script: `main` returns 0 on failure (in-script `\|\| true`) | `scripts/tests/test_install_apss_exporter.py::test_wrong_checksum_fails_and_installs_nothing`, `::test_other_arch_checksum_is_not_accepted`, `::test_wrong_reported_version_fails_and_installs_nothing`, `::test_missing_download_fails_and_installs_nothing` |
| `05-skip-version-check.patch` | script: `--version` check disabled | `scripts/tests/test_install_apss_exporter.py::test_wrong_reported_version_fails_and_installs_nothing` |
| `06-leave-temp-file.patch` | script: temp-file cleanup removed | `scripts/tests/test_install_apss_exporter.py::test_wrong_checksum_fails_and_installs_nothing`, `::test_other_arch_checksum_is_not_accepted`, `::test_wrong_reported_version_fails_and_installs_nothing`, `::test_missing_download_fails_and_installs_nothing` |

Dispatch:

```
just mutation-evidence 2130 "ci/fitness/infrastructure/test_syn_api_exporter_pin.py::test_install_runs_the_tested_script_with_no_shell scripts/tests/test_install_apss_exporter.py::test_wrong_checksum_fails_and_installs_nothing scripts/tests/test_install_apss_exporter.py::test_other_arch_checksum_is_not_accepted scripts/tests/test_install_apss_exporter.py::test_wrong_reported_version_fails_and_installs_nothing scripts/tests/test_install_apss_exporter.py::test_missing_download_fails_and_installs_nothing" false
```
