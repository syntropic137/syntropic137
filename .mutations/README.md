# Mutation evidence for #2391

Each patch is killed by
`apps/syn-api/tests/test_2391_command_phase_steps_read_back_over_http.py::test_a_command_phase_reads_back_every_step_it_was_installed_with`.

| Patch | Bug it re-introduces |
|---|---|
| `01-steps-reader-accepts-only-a-list.patch` | the fix reverted: `stored_command_steps` reads only a `list`, so the tuple the projection is handed stores `[]` |
| `02-step-mapping-drops-allow-failure.patch` | the API mapping drops `allow_failure` from each step |
