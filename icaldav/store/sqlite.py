"""SQLite-backed persistent implementation of the LocalStore protocol.

RFC References:
    - RFC 4791: CalDAV Core Specification (Resource & Collection Persistence).
    - RFC 4918: WebDAV Core Specification (ETag & Property Storage).
    - RFC 6578: WebDAV Collection Synchronization (Tombstone Tracking).
"""

from __future__ import annotations

import asyncio
import importlib.resources
import sqlite3
from pathlib import Path
from typing import Any

from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    ResourcePath,
    SyncChanges,
    SyncToken,
)


def _load_schema() -> str:
    """Load the SQLite schema definition from the package schema.sql file."""
    return (
        importlib.resources.files("icaldav.store")
        .joinpath("schema.sql")
        .read_text("utf-8")
    )


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
                schema_sql = _load_schema()
                self._conn.executescript(schema_sql)
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
            return SyncToken.from_sequence(row["sync_token_counter"]).uri
        return None

    async def get_sync_token(self, collection: CollectionPath | str) -> str | None:
        """Retrieve the latest DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        return await self._execute_sync(self._sync_get_sync_token, coll.canonical)

    def _sync_set_sync_token(self, coll_str: str, token: str) -> None:
        conn = self._get_connection()
        st = SyncToken.parse(token)
        conn.execute(
            """
            INSERT INTO collections (path, sync_token_counter)
            VALUES (?, ?)
            ON CONFLICT(path) DO UPDATE SET sync_token_counter = ?
            """,
            (coll_str, st.sequence, st.sequence),
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

    def _sync_initial_sync_changes(
        self,
        conn: sqlite3.Connection,
        coll_str: str,
        curr_token_str: str,
        limit: int | None,
    ) -> SyncChanges:
        query = (
            "SELECT path, etag, ics_data, uid, token_id FROM resources "
            "WHERE collection_path = ? ORDER BY token_id ASC, path ASC"
        )
        rows = conn.execute(query, (coll_str,)).fetchall()
        if limit is not None and limit > 0 and len(rows) > limit:
            selected_rows = rows[:limit]
            resources = [
                CalendarResource(
                    path=ResourcePath.parse(r["path"]),
                    etag=r["etag"],
                    ics_data=r["ics_data"],
                    uid=r["uid"],
                )
                for r in selected_rows
            ]
            last_token_id = selected_rows[-1]["token_id"]
            page_token = SyncToken.from_sequence(last_token_id).uri
            return SyncChanges(
                sync_token=page_token,
                changed=resources,
                deleted_hrefs=[],
                has_more=True,
            )

        resources = [
            CalendarResource(
                path=ResourcePath.parse(r["path"]),
                etag=r["etag"],
                ics_data=r["ics_data"],
                uid=r["uid"],
            )
            for r in rows
        ]
        return SyncChanges(
            sync_token=curr_token_str,
            changed=resources,
            deleted_hrefs=[],
            has_more=False,
        )

    def _sync_delta_sync_changes(
        self,
        conn: sqlite3.Connection,
        coll_str: str,
        token_num: int,
        curr_token_str: str,
        limit: int | None,
    ) -> SyncChanges:
        res_rows = conn.execute(
            """
            SELECT path, etag, ics_data, uid, token_id FROM resources
            WHERE collection_path = ? AND token_id > ?
            ORDER BY token_id ASC
            """,
            (coll_str, token_num),
        ).fetchall()

        tomb_rows = conn.execute(
            """
            SELECT path, token_id FROM tombstones
            WHERE collection_path = ? AND token_id > ?
            ORDER BY token_id ASC
            """,
            (coll_str, token_num),
        ).fetchall()

        changed_paths = {r["path"] for r in res_rows}
        all_changes: list[tuple[str, CalendarResource | str, int]] = []

        for r in res_rows:
            res = CalendarResource(
                path=ResourcePath.parse(r["path"]),
                etag=r["etag"],
                ics_data=r["ics_data"],
                uid=r["uid"],
            )
            all_changes.append(("changed", res, r["token_id"]))

        for t in tomb_rows:
            if t["path"] not in changed_paths:
                all_changes.append(("deleted", t["path"], t["token_id"]))

        all_changes.sort(key=lambda x: x[2])

        if limit is not None and limit > 0 and len(all_changes) > limit:
            selected = all_changes[:limit]
            has_more = True
            last_token_id = selected[-1][2]
            page_token = SyncToken.from_sequence(last_token_id).uri
        else:
            selected = all_changes
            has_more = False
            page_token = curr_token_str

        changed_res = [item[1] for item in selected if item[0] == "changed"]
        deleted_hrefs = [item[1] for item in selected if item[0] == "deleted"]

        return SyncChanges(
            sync_token=page_token,
            changed=changed_res,  # type: ignore[arg-type]
            deleted_hrefs=deleted_hrefs,  # type: ignore[arg-type]
            has_more=has_more,
        )

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
        curr_token_str = SyncToken.from_sequence(curr_counter).uri

        st = SyncToken.parse(token_str)
        if st.sequence == 0:
            return self._sync_initial_sync_changes(
                conn, coll_str, curr_token_str, limit
            )
        return self._sync_delta_sync_changes(
            conn, coll_str, st.sequence, curr_token_str, limit
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
