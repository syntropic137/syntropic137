#!/usr/bin/env python3
"""Event Store Validation Script.

Connects to the PostgreSQL event store and validates the event-sourcing setup
by querying for stored events. This is a development/debugging tool only.

Usage:
    uv run python scripts/validate_event_store.py
    just validate-events  # If added to justfile

Environment variables:
    DATABASE_URL: PostgreSQL connection string (default: postgres://localhost:5432/aef_dev)
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Add color support for terminal output
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"


def color(text: str, code: str) -> str:
    """Wrap text in ANSI color code."""
    return f"{code}{text}{RESET}"


def print_header(title: str) -> None:
    """Print a formatted header."""
    print(f"\n{color('=' * 60, DIM)}")
    print(color(f"  {title}", BOLD + CYAN))
    print(f"{color('=' * 60, DIM)}\n")


def print_event(event: dict[str, Any], index: int) -> None:
    """Pretty print an event."""
    print(f"{color(f'[{index}]', BOLD)} {color(event.get('event_type', 'Unknown'), YELLOW)}")
    print(
        f"    {color('Aggregate:', DIM)} {event.get('aggregate_type')}:{event.get('aggregate_id')}"
    )
    print(f"    {color('Version:', DIM)} {event.get('version')}")
    print(f"    {color('Timestamp:', DIM)} {event.get('created_at')}")

    # Print event data (truncated if too long)
    event_data = event.get("event_data", {})
    if event_data:
        data_str = str(event_data)
        if len(data_str) > 200:
            data_str = data_str[:200] + "..."
        print(f"    {color('Data:', DIM)} {data_str}")
    print()


def validate_event_store() -> int:
    """Connect to PostgreSQL and validate the event store."""
    try:
        import psycopg
    except ImportError:
        print(color("Error: psycopg is not installed.", RED))
        print("Install it with: uv add 'psycopg[binary]' --dev")
        return 1

    # Get database connection string
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://aef:aef_dev_password@localhost:5432/aef",
    )

    print_header("Event Store Validation")
    print(f"Connecting to: {color(database_url.split('@')[-1], CYAN)}")

    try:
        with psycopg.connect(database_url) as conn, conn.cursor() as cur:
            # Check if events table exists (Event Store Server uses 'events' table)
            cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'events'
                    );
                """)
            table_exists = cur.fetchone()[0]

            if not table_exists:
                print(color("⚠️  Events table does not exist yet.", YELLOW))
                print("   This is normal if no events have been stored.")

                # List all tables in the database
                cur.execute("""
                        SELECT table_name FROM information_schema.tables
                        WHERE table_schema = 'public'
                        ORDER BY table_name;
                    """)
                tables = cur.fetchall()
                if tables:
                    print(f"\n   Available tables: {', '.join(t[0] for t in tables)}")
                else:
                    print("   No tables found in the database.")
                return 0

            # Count total events
            cur.execute("SELECT COUNT(*) FROM events;")
            total_events = cur.fetchone()[0]
            print(f"\n{color('Total events stored:', BOLD)} {color(str(total_events), GREEN)}")

            if total_events == 0:
                print(color("\n⚠️  No events in the store yet.", YELLOW))
                print("   Run a workflow to generate events.")
                return 0

            # Get event counts by aggregate type
            print_header("Events by Aggregate Type")
            cur.execute("""
                    SELECT aggregate_type, COUNT(*) as count
                    FROM events
                    GROUP BY aggregate_type
                    ORDER BY count DESC;
                """)
            for row in cur.fetchall():
                print(f"  {color(row[0], CYAN)}: {row[1]} events")

            # Get event counts by event type
            print_header("Events by Event Type")
            cur.execute("""
                    SELECT event_type, COUNT(*) as count
                    FROM events
                    GROUP BY event_type
                    ORDER BY count DESC
                    LIMIT 15;
                """)
            for row in cur.fetchall():
                print(f"  {color(row[0], YELLOW)}: {row[1]}")

            # Show recent events
            print_header("Recent Events (last 10)")
            cur.execute("""
                    SELECT
                        event_id,
                        aggregate_type,
                        aggregate_id,
                        event_type,
                        event_version as version,
                        payload as event_data,
                        to_timestamp(recorded_time_unix_ms / 1000.0) as created_at
                    FROM events
                    ORDER BY recorded_time_unix_ms DESC
                    LIMIT 10;
                """)
            columns = [desc[0] for desc in cur.description]
            for idx, row in enumerate(cur.fetchall(), 1):
                event = dict(zip(columns, row, strict=True))
                print_event(event, idx)

            # Show workflow-specific events if any
            cur.execute("""
                    SELECT COUNT(*) FROM events
                    WHERE aggregate_type = 'Workflow';
                """)
            workflow_count = cur.fetchone()[0]

            if workflow_count > 0:
                print_header("Workflow Aggregates")
                cur.execute("""
                        SELECT DISTINCT aggregate_id
                        FROM events
                        WHERE aggregate_type = 'Workflow'
                        LIMIT 5;
                    """)
                for row in cur.fetchall():
                    workflow_id = row[0]
                    print(f"\n  {color('Workflow:', BOLD)} {workflow_id}")

                    # Get events for this workflow
                    cur.execute(
                        """
                            SELECT event_type, event_version, to_timestamp(recorded_time_unix_ms / 1000.0)
                            FROM events
                            WHERE aggregate_id = %s
                            ORDER BY event_version;
                        """,
                        (workflow_id,),
                    )
                    for event_row in cur.fetchall():
                        print(
                            f"    v{event_row[1]}: {color(event_row[0], YELLOW)} ({event_row[2]})"
                        )

            print(f"\n{color('✅ Event store validation complete!', GREEN)}\n")
            return 0

    except psycopg.OperationalError as e:
        print(color(f"\n❌ Connection failed: {e}", RED))
        print("\nMake sure Docker is running:")
        print(f"  {color('just dev', CYAN)}")
        return 1
    except Exception as e:
        print(color(f"\n❌ Error: {e}", RED))
        return 1


if __name__ == "__main__":
    sys.exit(validate_event_store())
