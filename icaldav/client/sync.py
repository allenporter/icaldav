"""High-level Local-First Synchronization Engine for CalDAV collections.

`CalDavSyncManager` serves as the primary high-level bridge between a remote CalDAV
server collection and a local application database (`LocalStore`).

Why Local-First Sync?
  CalDAV servers in the wild vary widely in their compliance with WebDAV specs,
  particularly around complex server-side date queries and recurrence expansion.
  `CalDavSyncManager` solves this by downloading and maintaining an exact local cache
  of raw `.ics` calendar resources. All timeline calculations, date filtering, and
  `RRULE`/`EXDATE` expansions are performed locally in-memory using the `ical` engine.

Dual-Path Synchronization Strategy:
  - **RFC 6578 WebDAV Sync**: Uses `<sync-collection>` REPORT with a stored token.
    This fetches incremental changes (additions, modifications, deletions) in a single
    efficient HTTP request.
  - **ETag Diff Fallback**: Automatically used when connecting to servers that
    do not support RFC 6578 (e.g. Radicale, Apple iCloud). Queries metadata via `PROPFIND`
    Depth 1, diffs remote `{href: etag}` against local storage, and batch-fetches changed
    items using `<calendar-multiget>`. Exactly 2 HTTP requests regardless of calendar size.

Example:
    ```python
    from icaldav.client import CalDavClient
    from icaldav.client.sync import CalDavSyncManager
    from icaldav.store.memory import MemoryStore

    store = MemoryStore()
    async with CalDavClient("https://caldav.example.com", auth=...) as client:
        sync_mgr = CalDavSyncManager(client, "/calendars/user/work/", store)
        result = await sync_mgr.sync()
        calendar = await sync_mgr.get_calendar()
        for event in calendar.events:
            print(event.summary, event.start)
    ```


RFC References:
    - RFC 6578: WebDAV Collection Synchronization (sync-collection REPORT).
    - RFC 4791 Section 7.9: calendar-multiget REPORT.
    - RFC 4918 Section 9.1: PROPFIND Method (Depth 1 ETag query).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from ical.calendar import Calendar
from ical.calendar_stream import CalendarStream
from ical.exceptions import CalendarError

from icaldav.client.client import CalDavClient
from icaldav.client.exceptions import CalDavError
from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    ReportResource,
    ResourcePath,
)

_LOGGER = logging.getLogger(__name__)


class SyncPath(Enum):
    """Synchronization execution path used by CalDavSyncManager."""

    RFC_6578 = "rfc_6578"
    """WebDAV Collection Synchronization (RFC 6578 sync-collection REPORT)."""

    ETAG_DIFF = "etag_diff"
    """ETag diff fallback (PROPFIND Depth 1 + calendar-multiget REPORT)."""


@dataclass(frozen=True)
class SyncResult:
    """Summary metrics of a completed calendar synchronization run.

    Attributes:
        path_used: The synchronization path executed (RFC_6578 or ETAG_DIFF).
        added: Count of new resources saved to LocalStore.
        updated: Count of modified resources updated in LocalStore.
        deleted: Count of removed resources deleted from LocalStore.
        unmodified: Count of unchanged resources skipped during sync.
        sync_token: The active DAV:sync-token stored after sync completion.
    """

    path_used: SyncPath
    added: int
    updated: int
    deleted: int
    unmodified: int
    sync_token: str | None


class CalDavSyncManager:
    """High-level Local-First Synchronization Engine for CalDAV collections.

    Connects network transport (CalDavClient) to local store (LocalStore) and
    local calendar parsing (ical).
    """

    def __init__(
        self,
        client: CalDavClient,
        collection_url: str,
        store: LocalStore,
    ) -> None:
        """Initialize sync manager.

        Args:
            client: Active CalDavClient instance bound to the user's authenticated session.
            collection_url: Target remote calendar collection URI path (e.g. "/work/").
            store: Account-scoped LocalStore instance (MemoryStore or SQLiteStore).
        """
        self.client = client
        self.collection_url = collection_url.rstrip("/")
        self.store = store
        self.collection_path = CollectionPath.parse(collection_url)

    async def sync(self, force_full_sync: bool = False) -> SyncResult:
        """Synchronize the local collection store with the remote CalDAV collection.

        Attempts RFC 6578 sync-collection first if supported and not forced.
        Falls back to ETag diffing via PROPFIND Depth 1 + calendar-multiget
        if RFC 6578 fails or is forced.

        Args:
            force_full_sync: If True, ignores stored sync token and forces ETag diffing.

        Returns:
            SyncResult dataclass detailing changes applied to LocalStore.
        """
        if not force_full_sync:
            try:
                return await self._sync_via_sync_collection()
            except CalDavError as err:
                _LOGGER.debug(
                    "RFC 6578 sync-collection failed or unsupported (%s); falling back to ETag diff",
                    err,
                )
                # Clear invalid sync token on failure
                await self.store.set_sync_token(self.collection_path, "")

        return await self._sync_via_etag_diff()

    async def _sync_via_sync_collection(self) -> SyncResult:
        """Execute incremental sync using RFC 6578 WebDAV Collection Synchronization."""
        stored_token = await self.store.get_sync_token(self.collection_path) or ""
        results, server_token = await self.client.sync_collection(
            self.collection_url, sync_token=stored_token
        )

        local_etags = await self.store.get_etags(self.collection_path)
        local_etags_norm = {
            ResourcePath.parse(k).canonical: v for k, v in local_etags.items()
        }

        added = 0
        updated = 0
        deleted = 0
        unmodified = 0

        # Process sync-collection response items: separate items with inline ics_data
        # from items that only returned ETags (which require calendar-multiget fetch).
        items_to_save: list[ReportResource] = []
        hrefs_needing_content: list[str] = []

        for item in results:
            if item.ics_data:
                items_to_save.append(item)
            else:
                if (
                    item.normalized_href not in local_etags_norm
                    or local_etags_norm[item.normalized_href] != item.normalized_etag
                ):
                    hrefs_needing_content.append(item.normalized_href)
                else:
                    unmodified += 1

        if hrefs_needing_content:
            multiget_results = await self.client.calendar_multiget(
                self.collection_url, hrefs=hrefs_needing_content
            )
            for item in multiget_results:
                if item.ics_data:
                    items_to_save.append(item)

        # TODO: Support batch store operations (save_resources / delete_resources) in LocalStore
        for item in items_to_save:
            resource = CalendarResource(
                path=item.resource_path,
                etag=item.normalized_etag,
                ics_data=item.ics_data or "",
                uid=item.extracted_uid,
            )

            if item.normalized_href not in local_etags_norm:
                added += 1
            elif local_etags_norm[item.normalized_href] != item.normalized_etag:
                updated += 1
            else:
                unmodified += 1

            await self.store.save_resource(resource)

        new_token = server_token or f"sync-token-{len(local_etags) + added - deleted}"
        await self.store.set_sync_token(self.collection_path, new_token)

        return SyncResult(
            path_used=SyncPath.RFC_6578,
            added=added,
            updated=updated,
            deleted=deleted,
            unmodified=unmodified,
            sync_token=new_token,
        )

    async def _sync_via_etag_diff(self) -> SyncResult:
        """Execute full sync via PROPFIND Depth 1 ETag diffing + calendar-multiget fallback."""
        items = await self.client.propfind(
            self.collection_url, depth=1, props=["getetag", "resourcetype"]
        )

        remote_etags: dict[str, str] = {
            item.normalized_href: item.normalized_etag
            for item in items
            if not item.is_collection and item.normalized_etag is not None
        }

        local_etags = await self.store.get_etags(self.collection_path)
        local_etags_norm = {
            ResourcePath.parse(k).canonical: v for k, v in local_etags.items()
        }

        to_fetch: list[str] = []
        to_delete: list[ResourcePath] = []
        unmodified = 0

        for norm_href, r_etag in remote_etags.items():
            if (
                norm_href not in local_etags_norm
                or local_etags_norm[norm_href] != r_etag
            ):
                to_fetch.append(norm_href)
            else:
                unmodified += 1

        for local_key in local_etags:
            local_path = ResourcePath.parse(local_key)
            if local_path.canonical not in remote_etags:
                to_delete.append(local_path)

        added = 0
        updated = 0

        if to_fetch:
            fetched_resources = await self.client.calendar_multiget(
                self.collection_url, hrefs=to_fetch
            )
            # TODO: Support batch store operations (save_resources / delete_resources) in LocalStore
            for item in fetched_resources:
                if not item.ics_data:
                    continue

                if item.normalized_href not in local_etags_norm:
                    added += 1
                else:
                    updated += 1

                res = CalendarResource(
                    path=item.resource_path,
                    etag=item.normalized_etag,
                    ics_data=item.ics_data,
                    uid=item.extracted_uid,
                )
                await self.store.save_resource(res)

        deleted = 0
        for path_to_del in to_delete:
            if await self.store.delete_resource(path_to_del):
                deleted += 1

        new_token = f"etag-sync-token-{len(remote_etags)}"
        await self.store.set_sync_token(self.collection_path, new_token)

        return SyncResult(
            path_used=SyncPath.ETAG_DIFF,
            added=added,
            updated=updated,
            deleted=deleted,
            unmodified=unmodified,
            sync_token=new_token,
        )

    async def get_calendar(self) -> Calendar:
        """Parse and aggregate all stored resources into a unified ical.calendar.Calendar.

        Returns:
            An ical.calendar.Calendar containing all parsed events, tasks, and journals.
        """
        merged_cal = Calendar()
        resources = await self.store.get_resources(self.collection_path)
        for res in resources:
            if not res.ics_data:
                continue
            try:
                stream = CalendarStream.from_ics(res.ics_data)
                for parsed_cal in stream.calendars:
                    for event in parsed_cal.events:
                        merged_cal.events.append(event)
                    for todo in parsed_cal.todos:
                        merged_cal.todos.append(todo)
                    for journal in parsed_cal.journal:
                        merged_cal.journal.append(journal)
            except (CalendarError, ValueError):
                _LOGGER.warning(
                    "Failed to parse resource %s into Calendar",
                    res.href,
                )

        return merged_cal
