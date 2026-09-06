# Experiment: can asyncpg and redis-py fetch a credential at connect time?

STATUS: IN PROGRESS (checkpoint commit — answers not yet filled in)

Infrastructure obtained in-workspace:
- PostgreSQL 16.2 (from PyPI `pgserver==0.1.4`) on 127.0.0.1:15499, scram-sha-256
- Redis 6.2.14 (from PyPI `redislite==6.2.912183`) on 127.0.0.1:16399, requirepass

Drivers under test (from the project venv): asyncpg 0.31.0, redis 7.4.0.
