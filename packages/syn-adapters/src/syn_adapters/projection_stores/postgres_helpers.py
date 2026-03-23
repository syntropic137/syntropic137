"""PostgreSQL projection store helpers.

Extracted from postgres_store.py to reduce module complexity.
"""

import json
from datetime import datetime
from typing import Any


def serialize(data: dict[str, Any]) -> str:
    """Serialize data to JSON, handling datetime objects."""
    return json.dumps(data, default=json_serializer)


def deserialize(data: str | dict[str, Any]) -> dict[str, Any]:
    """Deserialize JSON data."""
    if isinstance(data, dict):
        return data
    result: dict[str, Any] = json.loads(data)
    return result


def json_serializer(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def build_query(
    table_name: str,
    filters: dict[str, Any] | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[str, list[Any]]:
    """Build a parameterized query for projection records."""
    query = f"SELECT data FROM {table_name}"
    params: list[Any] = []
    param_idx = 1

    if filters:
        conditions = []
        for key, value in filters.items():
            conditions.append(f"data->>'{key}' = ${param_idx}")
            params.append(str(value))
            param_idx += 1
        query += " WHERE " + " AND ".join(conditions)

    if order_by:
        if order_by.startswith("-"):
            field = order_by[1:]
            direction = "DESC"
        else:
            field = order_by
            direction = "ASC"
        query += f" ORDER BY data->>'{field}' {direction}"
    else:
        query += " ORDER BY updated_at DESC"

    if limit:
        query += f" LIMIT {limit}"
    if offset:
        query += f" OFFSET {offset}"

    return query, params
