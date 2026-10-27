# #2122 mutation evidence

| Patch | Source | Test that kills it | Local |
|---|---|---|---|
| 01-compress-resets-mtime.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/local_archive.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 02-reference-fresh-mtime.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/local_archive.py` | `packages/syn-adapters/tests/test_session_archive_splice.py` | killed |
| 03-put-fresh-mtime.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/local_archive.py` | `packages/syn-adapters/tests/test_session_archive_splice.py` | killed |
| 04-no-week-window.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 05-day-window-is-week.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 06-temps-count-as-growth.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 07-references-not-counted.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 08-apparent-size.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 09-links-counted-twice.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 17-later-link-names-skipped.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 10-cache-never-expires.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 11-no-cache.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 12-walks-overlap.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 13-health-waits-for-walk.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 14-per-day-is-24h.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 15-runway-when-no-growth.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 16-health-drops-session-store.patch | `apps/syn-api/src/syn_api/services/lifecycle.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
