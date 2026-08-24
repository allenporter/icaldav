"""SQLite-backed persistent implementation of the PrincipalStore protocol.

RFC References:
    - RFC 3744 Section 2 & 4: WebDAV Access Control Protocol (Principals & Properties).
    - RFC 4791 Section 6.2: CalDAV Calendar Home & User Address Sets.
    - RFC 5397 Section 3: WebDAV Current Principal Extension.
"""

from __future__ import annotations

import asyncio
import importlib.resources
import sqlite3
from pathlib import Path
from typing import Any

from icaldav.store.principal import PrincipalInfo, PrincipalStore


def _load_schema() -> str:
    """Load the SQLite schema definition from the package schema.sql file."""
    return (
        importlib.resources.files("icaldav.store")
        .joinpath("schema.sql")
        .read_text("utf-8")
    )


class SQLitePrincipalStore(PrincipalStore):
    """Persistent multi-user principal directory store backed by SQLite.

    Features:
        - Full persistence of user accounts, principal paths, calendar home paths,
          emails, and display names across server restarts.
        - Case-insensitive search across user_id, email, and display_name.
        - Support for default principal resolution.
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        default_user_id: str | None = None,
        initial_principals: list[PrincipalInfo] | None = None,
    ) -> None:
        """Initialize SQLitePrincipalStore with database file path."""
        self._db_path = str(db_path)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None
        self._initialized = False
        self._default_user_id = default_user_id
        self._initial_principals = initial_principals

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
                if self._initial_principals:
                    for p in self._initial_principals:
                        is_def = 1 if (self._default_user_id == p.user_id) else 0
                        self._conn.execute(
                            """
                            INSERT INTO principals (user_id, principal_path, calendar_home_path, email, display_name, is_default)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                                principal_path = excluded.principal_path,
                                calendar_home_path = excluded.calendar_home_path,
                                email = excluded.email,
                                display_name = excluded.display_name,
                                is_default = excluded.is_default
                            """,
                            (
                                p.user_id,
                                p.principal_path,
                                p.calendar_home_path,
                                p.email,
                                p.display_name,
                                is_def,
                            ),
                        )
                    if self._default_user_id is None and self._initial_principals:
                        self._default_user_id = self._initial_principals[0].user_id
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

    @classmethod
    def create_single_user(
        cls,
        db_path: str | Path = ":memory:",
        user_id: str = "user",
        principal_path: str = "/principals/user/",
        calendar_home_path: str = "/",
        email: str = "mailto:user@localhost",
        display_name: str | None = None,
    ) -> SQLitePrincipalStore:
        """Factory method creating a single-user SQLite principal store."""
        p = PrincipalInfo(
            user_id=user_id,
            principal_path=principal_path,
            calendar_home_path=calendar_home_path,
            email=email,
            display_name=display_name,
        )
        return cls(
            db_path=db_path,
            default_user_id=user_id,
            initial_principals=[p],
        )

    def _sync_add_principal(self, principal: PrincipalInfo, is_default: bool) -> None:
        conn = self._get_connection()
        if is_default:
            conn.execute("UPDATE principals SET is_default = 0")
            self._default_user_id = principal.user_id

        conn.execute(
            """
            INSERT INTO principals (user_id, principal_path, calendar_home_path, email, display_name, is_default)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                principal_path = excluded.principal_path,
                calendar_home_path = excluded.calendar_home_path,
                email = excluded.email,
                display_name = excluded.display_name,
                is_default = excluded.is_default
            """,
            (
                principal.user_id,
                principal.principal_path,
                principal.calendar_home_path,
                principal.email,
                principal.display_name,
                1 if is_default else 0,
            ),
        )

    async def add_principal(
        self, principal: PrincipalInfo, is_default: bool = False
    ) -> None:
        """Register or update a PrincipalInfo entry in persistent SQLite storage.

        Args:
            principal: PrincipalInfo instance to store.
            is_default: Whether this principal should be treated as the default principal.
        """
        await self._execute_sync(self._sync_add_principal, principal, is_default)

    def _sync_get_principal(self, user_id: str | None) -> PrincipalInfo:
        conn = self._get_connection()
        target_id = user_id or self._default_user_id

        if target_id is not None:
            row = conn.execute(
                """
                SELECT user_id, principal_path, calendar_home_path, email, display_name
                FROM principals
                WHERE user_id = ?
                """,
                (target_id,),
            ).fetchone()
            if row is not None:
                return PrincipalInfo(
                    user_id=row["user_id"],
                    principal_path=row["principal_path"],
                    calendar_home_path=row["calendar_home_path"],
                    email=row["email"],
                    display_name=row["display_name"],
                )
            if user_id is not None:
                raise KeyError(f"Principal for user '{user_id}' not found")

        # If user_id was None and default_user_id wasn't found or not set, look for is_default = 1
        row = conn.execute(
            """
            SELECT user_id, principal_path, calendar_home_path, email, display_name
            FROM principals
            WHERE is_default = 1
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return PrincipalInfo(
                user_id=row["user_id"],
                principal_path=row["principal_path"],
                calendar_home_path=row["calendar_home_path"],
                email=row["email"],
                display_name=row["display_name"],
            )

        # Fallback to user 'user' or the first registered principal
        row = conn.execute(
            """
            SELECT user_id, principal_path, calendar_home_path, email, display_name
            FROM principals
            ORDER BY CASE WHEN user_id = 'user' THEN 0 ELSE 1 END, rowid ASC
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return PrincipalInfo(
                user_id=row["user_id"],
                principal_path=row["principal_path"],
                calendar_home_path=row["calendar_home_path"],
                email=row["email"],
                display_name=row["display_name"],
            )

        raise KeyError(f"Principal for user '{target_id}' not found")

    async def get_principal(self, user_id: str | None = None) -> PrincipalInfo:
        """Resolve PrincipalInfo by user_id or return the default principal.

        Args:
            user_id: Optional user ID to look up. If None, returns default user principal.

        Returns:
            PrincipalInfo object.

        Raises:
            KeyError: If user_id is provided but not found in the store, or store is empty.
        """
        return await self._execute_sync(self._sync_get_principal, user_id)

    def _sync_search_principals(self, match_str: str) -> list[PrincipalInfo]:
        conn = self._get_connection()
        pattern = f"%{match_str}%"
        rows = conn.execute(
            """
            SELECT user_id, principal_path, calendar_home_path, email, display_name
            FROM principals
            WHERE user_id LIKE ? COLLATE NOCASE
               OR email LIKE ? COLLATE NOCASE
               OR (display_name IS NOT NULL AND display_name LIKE ? COLLATE NOCASE)
            ORDER BY user_id ASC
            """,
            (pattern, pattern, pattern),
        ).fetchall()
        return [
            PrincipalInfo(
                user_id=row["user_id"],
                principal_path=row["principal_path"],
                calendar_home_path=row["calendar_home_path"],
                email=row["email"],
                display_name=row["display_name"],
            )
            for row in rows
        ]

    async def search_principals(self, match_str: str) -> list[PrincipalInfo]:
        """Search registered principals matching substring in user_id, email, or display_name.

        Args:
            match_str: Case-insensitive search substring.

        Returns:
            List of matching PrincipalInfo objects.
        """
        return await self._execute_sync(self._sync_search_principals, match_str)
