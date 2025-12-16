#!/usr/bin/env python3
import asyncio
import asyncpg
from datetime import datetime, UTC
import json

async def test_timescale():
    print("🔍 Testing TimescaleDB setup...")

    # 1. Connect
    conn = await asyncpg.connect(
        host='timescale-test',
        port=5432,
        user='test',
        password='test',
        database='obs_test'
    )
    print("✅ Connected to TimescaleDB")

    # 2. Create extension
    await conn.execute('CREATE EXTENSION IF NOT EXISTS timescaledb;')
    print("✅ TimescaleDB extension loaded")

    # 3. Create table
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS test_observations (
            time TIMESTAMPTZ NOT NULL,
            session_id TEXT NOT NULL,
            data JSONB
        )
    ''')
    print("✅ Table created")

    # 4. Create hypertable
    await conn.execute(
        "SELECT create_hypertable('test_observations', 'time', if_not_exists => TRUE)"
    )
    print("✅ Hypertable created")

    # 5. Insert test data
    await conn.execute('''
        INSERT INTO test_observations (time, session_id, data)
        VALUES ($1, $2, $3)
    ''', datetime.now(UTC), 'test-session', json.dumps({
        'input_tokens': 1000,
        'output_tokens': 500
    }))
    print("✅ Test data inserted")

    # 6. Query back
    row = await conn.fetchrow(
        'SELECT * FROM test_observations ORDER BY time DESC LIMIT 1'
    )
    print(f"✅ Query successful: {row['data']}")

    # 7. Test compression
    await conn.execute('''
        ALTER TABLE test_observations SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'session_id'
        )
    ''')
    print("✅ Compression configured")

    await conn.close()
    print("\n🎉 All tests passed! TimescaleDB is working!")

if __name__ == '__main__':
    asyncio.run(test_timescale())
