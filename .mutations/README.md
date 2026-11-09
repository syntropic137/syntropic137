# Mutation evidence for #2227

| patch | bug it re-introduces | killed by |
|---|---|---|
| 01-pids-candidate-not-settled | fork failure seen but never promoted at end of stream | `test_2227_a_phase_out_of_pids_says_so.py` (named-limit tests) |
| 02-handler-drops-pids-limit | handler builds the codex processor without the workspace's limit | `test_a_stream_cut_off_after_a_fork_failure_names_the_pids_limit` |
| 03-workspace-forgets-its-pids-limit | provisioning does not record the limit on `ManagedWorkspace` | `test_workspace_pids_request.py` (two tests) |
| 04-first-fork-failure-wins | an earlier fork failure outlives a later command that ran | `test_a_fork_failure_followed_by_a_command_that_ran_is_not_the_cause` |
