# Mutation patches for #2144 (pit stop collector warning)

Each one reintroduces a bug into `scripts/pit_stop_repoint.py`'s `--collector`
form. Kill with `scripts/tests/test_pit_stop_repoint.py::TestTheCollectorIsReportedNeverRefused`.

| patch | bug | killed by |
|---|---|---|
| 01-collector-comparison-inverted | warns on a match, silent on a mismatch | `test_the_release_digest_prints_nothing`, `test_an_older_digest_names_both` |
| 02-collector-mismatch-exits-non-zero | a mismatch fails the pit stop instead of reporting | every case that warns (`returncode == 0`) |
| 03-collector-tag-pin-treated-as-matching | a tag-pinned collector is silent | `test_a_tag_pinned_collector_differs_and_says_why` |
