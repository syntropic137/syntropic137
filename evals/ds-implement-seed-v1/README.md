# ds-implement-seed-v1 (#2178)

End-to-end quality gate for DreamShip workflows (`dreamship-implement-v5` and its variants).

- **Case:** a closed DreamShip bead. The repo is pinned at `commit` (the parent of the fix), and the
  task is the bead's own text plus the interface the oracle calls.
- **Oracle, written per case:** DreamShip keeps its tests inline (`mod tests` inside the edited
  file), so a fix's own tests cannot be hidden. A black-box test in `oracles/<case>/` calls only the
  stated interface and assumes no file layout.
- **Admission:** a case is admitted only when all three of these hold.
  1. The oracle FAILS at `commit`.
  2. It PASSES at `fix_commit`.
  3. A compiling mutant of the fix FAILS it. A failure at `commit` can be a compile error, which
     proves only that the names exist.
- **Pass, once scoring lands:** the oracle passes, plus `cargo test` + clippy, 0 Codex blockers and
  the scope judge (#2048).

## Admission log
| Case | Bead | at commit | at fix_commit | Mutant | Mutant result |
|---|---|---|---|---|---|
| markdown-portability | 181.3.10 | FAIL (E0432, exit 101) | PASS 4/4 | `import_markdown` returns `Default` | FAIL 2/4 |

Admission was run locally on 2026-11-05 with cargo on macOS and a shared target dir.
