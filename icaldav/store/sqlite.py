"""SQLite-backed persistent implementation of the LocalStore protocol.

RFC References:
    - RFC 4791: CalDAV Core Specification (Resource & Collection Persistence).
    - RFC 4918: WebDAV Core Specification (ETag & Property Storage).
    - RFC 6578: WebDAV Collection Synchronization (Tombstone Tracking).
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any

from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    ResourcePath,
    SyncChanges,
)

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS collections (
    path TEXT PRIMARY KEY,
    sync_token_counter INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS resources (
    path TEXT PRIMARY KEY,
    collection_path TEXT NOT NULL,
    etag TEXT NOT NULL,
    ics_data TEXT NOT NULL,
    uid TEXT,
    token_id INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(collection_path) REFERENCES collections(path) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tombstones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    collection_path TEXT NOT NULL,
    token_id INTEGER NOT NULL,
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(collection_path) REFERENCES collections(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_resources_collection ON resources(collection_path);
CREATE INDEX IF NOT EXISTS idx_tombstones_collection ON tombstones(collection_path);
"""


def _extract_token_int(token_str: str | None) -> int:
    """Extract integer sequence from a sync token URI or string."""
    if not token_str:
        return 0
    match = re.search(r"(\d+)$", token_str.strip())
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return 0


def _format_sync_token(counter: int) -> str:
    """Format integer counter as RFC 6578 sync-token URI."""
    return f"data:,{counter}"


class SQLiteStore(LocalStore):
    """Persistent calendar storage backed by an SQLite database.

    Features:
        - Full persistence across server/client restarts.
        - Incremental sync tokens per collection.
        - Deletion tombstone tracking for delta synchronization (RFC 6578).
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Initialize SQLiteStore with database file path."""
        self._db_path = str(db_path)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """Get or initialize SQLite connection and schema."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                autocommit=True,
            )
            self._conn.row_factory = sqlite3.Row
            if not self._initialized:
                self._conn.executescript(_SCHEMA)
                self._initialized = True
        return self._conn

    async def close(self) -> None:
        """Close the underlying SQLite connection."""
        async with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    async def _execute_sync(self, fn: Any, *args: Any) -> Any:
        """Run a synchronous database function in a thread with lock protection."""
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _sync_get_sync_token(self, coll_str: str) -> str | None:
        conn = self._get_connection()
        row = conn.execute(
            "SELECT sync_token_counter FROM collections WHERE path = ?",
            (coll_str,),
        ).fetchone()
        if row is not None:
            return _format_sync_token(row["sync_token_counter"])
        return None

    async def get_sync_token(self, collection: CollectionPath | str) -> str | None:
        """Retrieve the latest DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        return await self._execute_sync(self._sync_get_sync_token, coll.canonical)

    def _sync_set_sync_token(self, coll_str: str, token: str) -> None:
        conn = self._get_connection()
        token_num = _extract_token_int(token)
        conn.execute(
            """
            INSERT INTO collections (path, sync_token_counter)
            VALUES (?, ?)
            ON CONFLICT(path) DO UPDATE SET sync_token_counter = ?
            """,
            (coll_str, token_num, token_num),
        )

    async def set_sync_token(
        self, collection: CollectionPath | str, token: str
    ) -> None:
        """Store or update the DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        await self._execute_sync(self._sync_set_sync_token, coll.canonical, token)

    def _sync_get_etags(self, coll_str: str) -> dict[str, str]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT path, etag FROM resources WHERE collection_path = ?",
            (coll_str,),
        ).fetchall()
        return {row["path"]: row["etag"] for row in rows}

    async def get_etags(self, collection: CollectionPath | str) -> dict[str, str]:
        """Retrieve a mapping of resource href to etag for all items in a CollectionPath."""
        coll = CollectionPath.parse(collection)
        return await self._execute_sync(self._sync_get_etags, coll.canonical)

    def _sync_get_resource(self, res_str: str) -> CalendarResource | None:
        conn = self._get_connection()
        row = conn.execute(
            "SELECT path, etag, ics_data, uid FROM resources WHERE path = ?",
            (res_str,),
        ).fetchone()
        if row is not None:
            return CalendarResource(
                path=ResourcePath.parse(row["path"]),
                etag=row["etag"],
                ics_data=row["ics_data"],
                uid=row["uid"],
            )
        return None

    async def get_resource(self, path: ResourcePath | str) -> CalendarResource | None:
        """Retrieve a single calendar resource by its ResourcePath."""
        res_path = ResourcePath.parse(path)
        return await self._execute_sync(self._sync_get_resource, res_path.canonical)

    def _sync_save_resource(self, resource: CalendarResource) -> None:
        conn = self._get_connection()
        coll_str = resource.path.collection_path.canonical
        res_str = resource.path.canonical

        # Ensure collection exists and increment counter
        row = conn.execute(
            "SELECT sync_token_counter FROM collections WHERE path = ?",
            (coll_str,),
        ).fetchone()
        if row is None:
            new_counter = 1
            conn.execute(
                "INSERT INTO collections (path, sync_token_counter) VALUES (?, ?)",
                (coll_str, new_counter),
            )
        else:
            new_counter = row["sync_token_counter"] + 1
            conn.execute(
                "UPDATE collections SET sync_token_counter = ? WHERE path = ?",
                (new_counter, coll_str),
            )

        conn.execute(
            """
            INSERT INTO resources (path, collection_path, etag, ics_data, uid, token_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                etag = excluded.etag,
                ics_data = excluded.ics_data,
                uid = excluded.uid,
                token_id = excluded.token_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                res_str,
                coll_str,
                resource.etag,
                resource.ics_data,
                resource.uid,
                new_counter,
            ),
        )

    async def save_resource(self, resource: CalendarResource) -> None:
        """Save or overwrite a calendar object resource in SQLite storage."""
        await self._execute_sync(self._sync_save_resource, resource)

    def _sync_delete_resource(self, res_str: str) -> bool:
        conn = self._get_connection()
        res_path = ResourcePath.parse(res_str)
        coll_str = res_path.collection_path.canonical

        existing = conn.execute(
            "SELECT path FROM resources WHERE path = ?",
            (res_str,),
        ).fetchone()
        if existing is None:
            return False

        # Advance collection sync token
        row = conn.execute(
            "SELECT sync_token_counter FROM collections WHERE path = ?",
            (coll_str,),
        ).fetchone()
        new_counter = (row["sync_token_counter"] + 1) if row else 1
        if row:
            conn.execute(
                "UPDATE collections SET sync_token_counter = ? WHERE path = ?",
                (new_counter, coll_str),
            )
        else:
            conn.execute(
                "INSERT INTO collections (path, sync_token_counter) VALUES (?, ?)",
                (coll_str, new_counter),
            )

        # Delete resource and insert tombstone
        conn.execute("DELETE FROM resources WHERE path = ?", (res_str,))
        conn.execute(
            "INSERT INTO tombstones (path, collection_path, token_id) VALUES (?, ?, ?)",
            (res_str, coll_str, new_counter),
        )
        return True

    async def delete_resource(self, path: ResourcePath | str) -> bool:
        """Delete a calendar object resource and record a tombstone."""
        res_path = ResourcePath.parse(path)
        return await self._execute_sync(self._sync_delete_resource, res_path.canonical)

    def _sync_get_resources(self, coll_str: str) -> list[CalendarResource]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT path, etag, ics_data, uid FROM resources WHERE collection_path = ?",
            (coll_str,),
        ).fetchall()
        return [
            CalendarResource(
                path=ResourcePath.parse(row["path"]),
                etag=row["etag"],
                ics_data=row["ics_data"],
                uid=row["uid"],
            )
            for row in rows
        ]

    async def get_resources(
        self, collection: CollectionPath | str
    ) -> list[CalendarResource]:
        """Retrieve all calendar resources in a CollectionPath."""
        coll = CollectionPath.parse(collection)
        return await self._execute_sync(self._sync_get_resources, coll.canonical)

    def _sync_collection_exists(self, coll_str: str) -> bool:
        conn = self._get_connection()
        row = conn.execute(
            "SELECT 1 FROM collections WHERE path = ?",
            (coll_str,),
        ).fetchone()
        return row is not None

    async def collection_exists(self, collection: CollectionPath | str) -> bool:
        """Check whether a CollectionPath exists in the store."""
        coll = CollectionPath.parse(collection)
        return await self._execute_sync(self._sync_collection_exists, coll.canonical)

    def _sync_create_collection(self, coll_str: str) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO collections (path, sync_token_counter)
            VALUES (?, 0)
            ON CONFLICT(path) DO NOTHING
            """,
            (coll_str,),
        )

    async def create_collection(self, collection: CollectionPath | str) -> None:
        """Create a new empty calendar collection."""
        coll = CollectionPath.parse(collection)
        await self._execute_sync(self._sync_create_collection, coll.canonical)

    def _sync_get_changes_since(
        self,
        coll_str: str,
        token_str: str | None,
        limit: int | None,
    ) -> SyncChanges:
        conn = self._get_connection()
        coll_row = conn.execute(
            "SELECT sync_token_counter FROM collections WHERE path = ?",
            (coll_str,),
        ).fetchone()
        curr_counter = coll_row["sync_token_counter"] if coll_row else 0
        curr_token_str = _format_sync_token(curr_counter)

        token_num = _extract_token_int(token_str)

        if token_num == 0:
            # Initial sync: return all current resources, zero tombstones
            query = "SELECT path, etag, ics_data, uid FROM resources WHERE collection_path = ? ORDER BY path ASC"
            rows = conn.execute(query, (coll_str,)).fetchall()
            resources = [
                CalendarResource(
                    path=ResourcePath.parse(r["path"]),
                    etag=r["etag"],
                    ics_data=r["ics_data"],
                    uid=r["uid"],
                )
                for r in rows
            ]
            has_more = False
            if limit is not None and limit > 0 and len(resources) > limit:
                resources = resources[:limit]
                has_more = True
            return SyncChanges(
                sync_token=curr_token_str,
                changed=resources,
                deleted_hrefs=[],
                has_more=has_more,
            )

        # Delta sync: fetch resources modified since token_num
        res_rows = conn.execute(
            """
            SELECT path, etag, ics_data, uid FROM resources
            WHERE collection_path = ? AND token_id > ?
            ORDER BY token_id ASC
            """,
            (coll_str, token_num),
        ).fetchall()
        changed_res = [
            CalendarResource(
                path=ResourcePath.parse(r["path"]),
                etag=r["etag"],
                ics_data=r["ics_data"],
                uid=r["uid"],
            )
            for r in res_rows
        ]

        # Fetch tombstones since token_num
        tomb_rows = conn.execute(
            """
            SELECT path FROM tombstones
            WHERE collection_path = ? AND token_id > ?
            ORDER BY token_id ASC
            """,
            (coll_str, token_num),
        ).fetchall()

        # Filter out tombstones if the resource was re-created in changed_res
        changed_paths = {r.path.canonical for r in changed_res}
        deleted_hrefs = [r["path"] for r in tomb_rows if r["path"] not in changed_paths]

        # Handle limits and pagination
        total_count = len(changed_res) + len(deleted_hrefs)
        has_more = False
        if limit is not None and limit > 0 and total_count > limit:
            has_more = True
            if len(changed_res) >= limit:
                changed_res = changed_res[:limit]
                deleted_hrefs = []
            else:
                remaining = limit - len(changed_res)
                deleted_hrefs = deleted_hrefs[:remaining]

        return SyncChanges(
            sync_token=curr_token_str,
            changed=changed_res,
            deleted_hrefs=deleted_hrefs,
            has_more=has_more,
        )

    async def get_changes_since(
        self,
        collection: CollectionPath | str,
        sync_token: str | None = None,
        limit: int | None = None,
    ) -> SyncChanges:
        """Retrieve modified and deleted resources in a CollectionPath since a sync token."""
        coll = CollectionPath.parse(collection)
        return await self._execute_sync(
            self._sync_get_changes_since,
            coll.canonical,
            sync_token,
            limit,
        )
