# Mutation evidence for #2221 (PR #2376)

Tests: `apps/syn-api/tests/test_2221_reclaim_repo_free_unowned.py` (no Docker; `docker=false`).

| Patch | Bug | Killed by (locally) |
|---|---|---|
| 01-repo-check-skipped | no repository probe on unowned dirs | git dir at depth, gitfile, worktree, bare, bare shape, made under the claim, walk past budget |
| 02-age-from-mtime | age read from mtime | new dir with an old mtime; listing ages by ctime |
| 03-setting-ignored | production wiring drops the setting | production reclaimer reads the setting |
| 04-recheck-skipped | no probe of the claimed path | a repository made under the claim keeps it |
| 05-age-reread-after-claim | age taken from the post-rename rescan | age is the one listed before the claim |
