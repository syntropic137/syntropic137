# Mutation patches for #2378

Tests: `apps/syn-api/tests/test_2378_rejudge_before_delete.py`

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-no-final-judgment-in-reclaim.patch` | `_reclaim` deletes after the mark without the final judgment | `test_a_commit_made_after_the_mark_keeps_the_dir_and_revokes_its_authorization` |
| `02-no-final-judgment-in-resume.patch` | `_resume_delete` deletes without judging the contents | `test_a_resumed_delete_whose_repo_is_now_unpushed_is_kept` |
| `03-keep-does-not-revoke.patch` | a keep at the final judgment leaves the authorization | both hazard tests (the first also through a later pass that would finish the delete) |
| `04-final-judgment-skips-git-guard.patch` | the final judgment runs the judge but not `guard_stale_workspace_dir` | both hazard tests |
