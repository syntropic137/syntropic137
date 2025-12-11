"""PostgreSQL storage implementation for UI Feedback."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import asyncpg

from ui_feedback.models import (
    FeedbackCreate,
    FeedbackItem,
    FeedbackItemWithMedia,
    FeedbackStats,
    FeedbackUpdate,
    MediaItem,
    MediaSummary,
    PriorityCount,
    StatusCount,
    TypeCount,
)
from ui_feedback.storage.protocol import FeedbackStorageProtocol

# Path to migrations directory
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


class PostgresFeedbackStorage(FeedbackStorageProtocol):
    """PostgreSQL implementation of feedback storage."""

    def __init__(self, database_url: str, auto_migrate: bool = True) -> None:
        self.database_url = database_url
        self.auto_migrate = auto_migrate
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool, raising if not connected."""
        if self._pool is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        return self._pool

    async def connect(self) -> None:
        """Initialize connection pool and run migrations if needed."""
        self._pool = await asyncpg.create_pool(self.database_url, min_size=2, max_size=10)

        # Auto-migrate on connect (idempotent - uses IF NOT EXISTS)
        if self.auto_migrate:
            await self._run_migrations()

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _run_migrations(self) -> None:
        """Run database migrations (idempotent - safe to run multiple times)."""
        migration_file = MIGRATIONS_DIR / "001_feedback_tables.sql"
        if not migration_file.exists():
            print(f"Warning: Migration file not found: {migration_file}")
            return

        sql = migration_file.read_text()

        async with self.pool.acquire() as conn:
            # Execute the migration SQL
            # All statements use IF NOT EXISTS, so this is idempotent
            await conn.execute(sql)
            print("✅ Database migrations applied (feedback_items, feedback_media)")

    # =========================================================
    # Feedback CRUD
    # =========================================================

    async def create_feedback(self, data: FeedbackCreate) -> FeedbackItem:
        """Create a new feedback item."""
        query = """
            INSERT INTO feedback_items (
                url, route, viewport_width, viewport_height,
                click_x, click_y, css_selector, xpath, component_name,
                feedback_type, comment, priority,
                app_name, app_version, user_agent,
                environment, git_commit, git_branch, hostname
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                $16, $17, $18, $19
            )
            RETURNING *
        """
        row = await self.pool.fetchrow(
            query,
            data.url,
            data.route,
            data.viewport_width,
            data.viewport_height,
            data.click_x,
            data.click_y,
            data.css_selector,
            data.xpath,
            data.component_name,
            data.feedback_type,
            data.comment,
            data.priority,
            data.app_name,
            data.app_version,
            data.user_agent,
            data.environment,
            data.git_commit,
            data.git_branch,
            data.hostname,
        )
        return self._row_to_feedback_item(row, media_count=0)

    async def get_feedback(self, feedback_id: UUID) -> FeedbackItemWithMedia | None:
        """Get a single feedback item with media metadata."""
        # Get feedback item
        query = "SELECT * FROM feedback_items WHERE id = $1"
        row = await self.pool.fetchrow(query, feedback_id)
        if not row:
            return None

        # Get media metadata
        media_query = """
            SELECT id, media_type, mime_type, file_name, file_size, created_at
            FROM feedback_media
            WHERE feedback_id = $1
            ORDER BY created_at
        """
        media_rows = await self.pool.fetch(media_query, feedback_id)

        media = [
            MediaSummary(
                id=m["id"],
                media_type=m["media_type"],
                mime_type=m["mime_type"],
                file_name=m["file_name"],
                file_size=m["file_size"],
                created_at=m["created_at"],
            )
            for m in media_rows
        ]

        return FeedbackItemWithMedia(
            **self._row_to_feedback_item(row, media_count=len(media)).model_dump(),
            media=media,
        )

    async def list_feedback(
        self,
        *,
        status: str | None = None,
        feedback_type: str | None = None,
        priority: str | None = None,
        app_name: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> tuple[list[FeedbackItem], int]:
        """List feedback items with filtering and pagination."""
        # Build WHERE clause
        conditions: list[str] = []
        params: list[str | int] = []
        param_idx = 1

        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if feedback_type:
            conditions.append(f"feedback_type = ${param_idx}")
            params.append(feedback_type)
            param_idx += 1

        if priority:
            conditions.append(f"priority = ${param_idx}")
            params.append(priority)
            param_idx += 1

        if app_name:
            conditions.append(f"app_name = ${param_idx}")
            params.append(app_name)
            param_idx += 1

        if search:
            conditions.append(f"comment ILIKE ${param_idx}")
            params.append(f"%{search}%")
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        # Validate order_by to prevent SQL injection
        allowed_order_fields = {"created_at", "updated_at", "priority", "status"}
        if order_by not in allowed_order_fields:
            order_by = "created_at"

        order_direction = "DESC" if order_desc else "ASC"
        offset = (page - 1) * page_size

        # Get total count
        count_query = f"SELECT COUNT(*) FROM feedback_items WHERE {where_clause}"
        total = await self.pool.fetchval(count_query, *params)

        # Get items with media count
        query = f"""
            SELECT f.*,
                   COALESCE(m.media_count, 0) as media_count
            FROM feedback_items f
            LEFT JOIN (
                SELECT feedback_id, COUNT(*) as media_count
                FROM feedback_media
                GROUP BY feedback_id
            ) m ON f.id = m.feedback_id
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([page_size, offset])

        rows = await self.pool.fetch(query, *params)
        items = [self._row_to_feedback_item(row, row["media_count"]) for row in rows]

        return items, total

    async def update_feedback(
        self, feedback_id: UUID, data: FeedbackUpdate
    ) -> FeedbackItem | None:
        """Update a feedback item."""
        # Build SET clause dynamically
        updates: list[str] = []
        params: list[str | UUID] = []
        param_idx = 1

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                updates.append(f"{field} = ${param_idx}")
                params.append(value)
                param_idx += 1

        if not updates:
            # Nothing to update, just return current state
            return await self._get_feedback_item(feedback_id)

        # Handle resolved_at timestamp
        if data.status == "resolved":
            updates.append(f"resolved_at = ${param_idx}")
            params.append(datetime.now(timezone.utc))
            param_idx += 1

        params.append(feedback_id)
        set_clause = ", ".join(updates)

        query = f"""
            UPDATE feedback_items
            SET {set_clause}
            WHERE id = ${param_idx}
            RETURNING *
        """

        row = await self.pool.fetchrow(query, *params)
        if not row:
            return None

        # Get media count
        media_count = await self.pool.fetchval(
            "SELECT COUNT(*) FROM feedback_media WHERE feedback_id = $1", feedback_id
        )

        return self._row_to_feedback_item(row, media_count)

    async def delete_feedback(self, feedback_id: UUID) -> bool:
        """Delete a feedback item (media deleted via CASCADE)."""
        query = "DELETE FROM feedback_items WHERE id = $1 RETURNING id"
        result = await self.pool.fetchval(query, feedback_id)
        return result is not None

    # =========================================================
    # Media CRUD
    # =========================================================

    async def create_media(
        self,
        feedback_id: UUID,
        media_type: str,
        mime_type: str,
        data: bytes,
        file_name: str | None = None,
    ) -> MediaItem:
        """Create a new media attachment."""
        query = """
            INSERT INTO feedback_media (
                feedback_id, media_type, mime_type, file_name, file_size, data
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, feedback_id, media_type, mime_type, file_name, file_size,
                      external_url, created_at
        """
        row = await self.pool.fetchrow(
            query, feedback_id, media_type, mime_type, file_name, len(data), data
        )
        return MediaItem(
            id=row["id"],
            feedback_id=row["feedback_id"],
            media_type=row["media_type"],
            mime_type=row["mime_type"],
            file_name=row["file_name"],
            file_size=row["file_size"],
            external_url=row["external_url"],
            created_at=row["created_at"],
        )

    async def get_media(self, media_id: UUID) -> tuple[MediaItem, bytes] | None:
        """Get media item with binary data."""
        query = """
            SELECT id, feedback_id, media_type, mime_type, file_name, file_size,
                   external_url, created_at, data
            FROM feedback_media
            WHERE id = $1
        """
        row = await self.pool.fetchrow(query, media_id)
        if not row:
            return None

        item = MediaItem(
            id=row["id"],
            feedback_id=row["feedback_id"],
            media_type=row["media_type"],
            mime_type=row["mime_type"],
            file_name=row["file_name"],
            file_size=row["file_size"],
            external_url=row["external_url"],
            created_at=row["created_at"],
        )
        return item, row["data"]

    async def delete_media(self, media_id: UUID) -> bool:
        """Delete a media attachment."""
        query = "DELETE FROM feedback_media WHERE id = $1 RETURNING id"
        result = await self.pool.fetchval(query, media_id)
        return result is not None

    # =========================================================
    # Stats
    # =========================================================

    async def get_stats(self, app_name: str | None = None) -> FeedbackStats:
        """Get aggregate statistics."""
        where_clause = "WHERE app_name = $1" if app_name else ""
        params = [app_name] if app_name else []

        # Total count
        total = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM feedback_items {where_clause}", *params
        )

        # By status
        status_query = f"""
            SELECT status, COUNT(*) as count
            FROM feedback_items {where_clause}
            GROUP BY status
        """
        status_rows = await self.pool.fetch(status_query, *params)
        by_status = StatusCount()
        for row in status_rows:
            setattr(by_status, row["status"], row["count"])

        # By type
        type_query = f"""
            SELECT feedback_type, COUNT(*) as count
            FROM feedback_items {where_clause}
            GROUP BY feedback_type
        """
        type_rows = await self.pool.fetch(type_query, *params)
        by_type = TypeCount()
        for row in type_rows:
            setattr(by_type, row["feedback_type"], row["count"])

        # By priority
        priority_query = f"""
            SELECT priority, COUNT(*) as count
            FROM feedback_items {where_clause}
            GROUP BY priority
        """
        priority_rows = await self.pool.fetch(priority_query, *params)
        by_priority = PriorityCount()
        for row in priority_rows:
            setattr(by_priority, row["priority"], row["count"])

        # By app (only if not filtering by app)
        by_app: dict[str, int] = {}
        if not app_name:
            app_query = """
                SELECT app_name, COUNT(*) as count
                FROM feedback_items
                GROUP BY app_name
            """
            app_rows = await self.pool.fetch(app_query)
            by_app = {row["app_name"]: row["count"] for row in app_rows}

        return FeedbackStats(
            total=total,
            by_status=by_status,
            by_type=by_type,
            by_priority=by_priority,
            by_app=by_app,
        )

    # =========================================================
    # Helpers
    # =========================================================

    async def _get_feedback_item(self, feedback_id: UUID) -> FeedbackItem | None:
        """Get feedback item without media details."""
        query = "SELECT * FROM feedback_items WHERE id = $1"
        row = await self.pool.fetchrow(query, feedback_id)
        if not row:
            return None
        media_count = await self.pool.fetchval(
            "SELECT COUNT(*) FROM feedback_media WHERE feedback_id = $1", feedback_id
        )
        return self._row_to_feedback_item(row, media_count)

    @staticmethod
    def _row_to_feedback_item(row: asyncpg.Record, media_count: int) -> FeedbackItem:
        """Convert a database row to FeedbackItem model."""
        return FeedbackItem(
            id=row["id"],
            url=row["url"],
            route=row["route"],
            viewport_width=row["viewport_width"],
            viewport_height=row["viewport_height"],
            click_x=row["click_x"],
            click_y=row["click_y"],
            css_selector=row["css_selector"],
            xpath=row["xpath"],
            component_name=row["component_name"],
            feedback_type=row["feedback_type"],
            comment=row["comment"],
            status=row["status"],
            priority=row["priority"],
            assigned_to=row["assigned_to"],
            resolution_notes=row["resolution_notes"],
            app_name=row["app_name"],
            app_version=row["app_version"],
            user_agent=row["user_agent"],
            environment=row["environment"],
            git_commit=row["git_commit"],
            git_branch=row["git_branch"],
            hostname=row["hostname"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_at=row["resolved_at"],
            media_count=media_count,
        )
