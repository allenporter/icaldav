"""Storage interfaces and data structures for icaldav.

RFC References:
  - RFC 4918 Section 14.16: DAV:getetag definition.
  - RFC 6578 Section 3: DAV:sync-token definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from typing import Protocol

from yarl import URL

from icaldav.store.principal import PrincipalInfo


@dataclass(frozen=True)
class CollectionPath:
    """Strongly-typed, immutable value object for a normalized CalDAV collection URI path."""

    path: str

    @classmethod
    def parse(cls, raw: str | CollectionPath) -> CollectionPath:
        """Factory creating a CollectionPath from a string or existing CollectionPath."""
        if isinstance(raw, CollectionPath):
            return raw
        p = URL(str(raw)).path.strip()
        if not p.startswith("/"):
            p = "/" + p
        clean = p.rstrip("/") if p != "/" else p
        return cls(path=clean)

    @property
    def canonical(self) -> str:
        """Return the canonical string path."""
        return self.path

    def __str__(self) -> str:
        return self.path

    def __repr__(self) -> str:
        return f"CollectionPath('{self.path}')"


@dataclass(frozen=True)
class ResourcePath:
    """Strongly-typed, immutable value object for a normalized CalDAV resource URI path."""

    path: str

    @classmethod
    def parse(cls, raw: str | ResourcePath) -> ResourcePath:
        """Factory creating a ResourcePath from a string or existing ResourcePath."""
        if isinstance(raw, ResourcePath):
            return raw
        p = URL(str(raw)).path.strip()
        if not p.startswith("/"):
            p = "/" + p
        clean = p.rstrip("/") if p != "/" else p
        return cls(path=clean)

    @cached_property
    def collection_path(self) -> CollectionPath:
        """Derive the parent CollectionPath."""
        parent_str = self.path.rsplit("/", 1)[0]
        return CollectionPath.parse(parent_str)

    @cached_property
    def filename(self) -> str:
        """Extract the filename component (e.g. 'event1.ics')."""
        return self.path.rsplit("/", 1)[-1]

    @property
    def canonical(self) -> str:
        """Return the canonical string path."""
        return self.path

    def __str__(self) -> str:
        return self.path

    def __repr__(self) -> str:
        return f"ResourcePath('{self.path}')"


@dataclass(frozen=True)
class CalendarResource:
    """Represents a calendar object resource stored within a collection.

    RFC References:
        - RFC 4791 Section 4.1: Calendar Collections.
        - RFC 4791 Section 5.2: Calendar Object Resources.
        - RFC 4918 Section 14.16: DAV:getetag.
    """

    path: ResourcePath
    """The strongly-typed ResourcePath (e.g. ResourcePath('/work/event1.ics'))."""

    etag: str
    """The entity tag representing the current version state of the resource."""

    ics_data: str
    """The raw RFC 5545 iCalendar content."""

    uid: str | None = None
    """The optional VEVENT/VTODO UID extracted from the iCalendar content."""

    @property
    def href(self) -> str:
        """Return canonical href string for backwards compatibility."""
        return self.path.canonical


class LocalStore(Protocol):
    """Abstract protocol for local calendar resource and sync token persistence.

    Store Granularity & Architecture:
      - A single `LocalStore` instance represents the local database for an application or engine.
      - Each collection is identified by its strongly-typed `CollectionPath` (e.g. CollectionPath('/work')).
      - Every resource is self-contained and identified by its strongly-typed `ResourcePath` (e.g. ResourcePath('/work/event1.ics')).
      - Implementations include `MemoryStore` (in-memory caching/testing) and `SQLiteStore` (persistent disk storage).
    """

    async def get_sync_token(self, collection: CollectionPath) -> str | None:
        """Retrieve the latest DAV:sync-token for a given CollectionPath.

        RFC Reference:
            - RFC 6578 Section 3: The DAV:sync-token Property.

        Args:
            collection: CollectionPath object for the calendar collection.

        Returns:
            The current sync token string, or None if no token exists.
        """
        ...

    async def set_sync_token(self, collection: CollectionPath, token: str) -> None:
        """Store or update the DAV:sync-token for a given CollectionPath.

        RFC Reference:
            - RFC 6578 Section 3: The DAV:sync-token Property.

        Args:
            collection: CollectionPath object for the calendar collection.
            token: The new sync token string.
        """
        ...

    async def get_etags(self, collection: CollectionPath) -> dict[str, str]:
        """Retrieve a mapping of resource href string to etag for all items in a CollectionPath.

        RFC Reference:
            - RFC 4918 Section 14.16: DAV:getetag.

        Args:
            collection: CollectionPath object for the calendar collection.

        Returns:
            A dictionary mapping resource href string to etag string.
        """
        ...

    async def get_resource(self, path: ResourcePath) -> CalendarResource | None:
        """Retrieve a single calendar resource by its ResourcePath.

        RFC Reference:
            - RFC 4791 Section 5.2: Calendar Object Resources.

        Args:
            path: The strongly-typed ResourcePath object (e.g. ResourcePath('/work/event1.ics')).

        Returns:
            The CalendarResource object if found, or None.
        """
        ...

    async def save_resource(self, resource: CalendarResource) -> None:
        """Save or overwrite a calendar object resource in local storage.

        RFC Reference:
            - RFC 4791 Section 5.3.1: Creating Calendar Object Resources.

        Args:
            resource: The CalendarResource object to persist.
        """
        ...

    async def delete_resource(self, path: ResourcePath) -> bool:
        """Delete a calendar object resource from local storage by its ResourcePath.

        RFC Reference:
            - RFC 4918 Section 9.7: DELETE Method.

        Args:
            path: The strongly-typed ResourcePath object (e.g. ResourcePath('/work/event1.ics')).

        Returns:
            True if the resource was deleted, False if it did not exist.
        """
        ...

    async def get_resources(self, collection: CollectionPath) -> list[CalendarResource]:
        """Retrieve all calendar resources in a CollectionPath.

        Used by calendar-query REPORT (RFC 4791 §7.8) to load all resources
        for server-side filtering by component type and time range.

        Args:
            collection: CollectionPath object for the calendar collection.

        Returns:
            List of all CalendarResource objects in the collection.
        """
        ...

    async def collection_exists(self, collection: CollectionPath) -> bool:
        """Check whether a CollectionPath exists in the store.

        Used by MKCALENDAR (RFC 4791 §5.3.1) to prevent duplicate creation,
        and by REPORT handlers to validate the target collection.

        Args:
            collection: CollectionPath object for the calendar collection.

        Returns:
            True if the collection exists, False otherwise.
        """
        ...

    async def create_collection(self, collection: CollectionPath) -> None:
        """Create a new empty calendar collection.

        Called by MKCALENDAR (RFC 4791 §5.3.1) to provision a new calendar
        collection with resource types DAV:collection and CALDAV:calendar.

        Args:
            collection: CollectionPath object for the new calendar collection.
        """
        ...

    async def get_changes_since(
        self,
        collection: CollectionPath,
        sync_token: str | None = None,
        limit: int | None = None,
    ) -> SyncChanges:
        """Retrieve modified and deleted resources in a CollectionPath since a sync token.

        RFC Reference:
            - RFC 6578 Section 3.2: sync-collection Report.

        Args:
            collection: CollectionPath object for the calendar collection.
            sync_token: The previous sync token, or None/empty for initial sync.
            limit: Optional maximum number of results to return.

        Returns:
            SyncChanges containing changed resources, deleted hrefs, and the updated sync token.
        """
        ...


@dataclass(frozen=True)
class SyncChanges:
    """Represents a delta synchronization result for a collection (RFC 6578).

    Attributes:
        sync_token: The new sync token representing this sync state.
        changed: List of new or modified CalendarResource items.
        deleted_hrefs: List of resource href strings deleted since the previous token.
        has_more: Whether there are additional pages of changes available (for pagination limits).
    """

    sync_token: str
    changed: list[CalendarResource]
    deleted_hrefs: list[str]
    has_more: bool = False


class ResourceKind(StrEnum):
    """Resource entity classification for WebDAV/CalDAV resources."""

    PRINCIPAL = "principal"
    ROOT = "root"
    CALENDAR = "calendar"
    RESOURCE = "resource"


@dataclass(frozen=True)
class ResourceTarget:
    """Domain model capturing target resource context for WebDAV property responses.

    Attributes:
        href: Canonical relative URI path string (e.g. "/", "/principals/user/", "/work/").
        kind: Explicit ResourceKind classification.
        displayname: Optional human-readable display name string.
        etag: Optional entity tag string for cache control.
        ctag: Optional collection change tag string for fast client sync diffing.
        sync_token: Optional synchronization token URI for RFC 6578 WebDAV Sync.
        principal: Optional PrincipalInfo metadata object for WebDAV autodiscovery properties.
    """

    href: str
    kind: ResourceKind
    displayname: str | None = None
    etag: str | None = None
    ctag: str | None = None
    sync_token: str | None = None
    principal: PrincipalInfo | None = None


@dataclass
class ReportResource:
    """A single resource entry in a REPORT 207 Multi-Status response.

    Attributes:
        href: Resource URI path.
        etag: Entity tag for version tracking.
        ics_data: Raw iCalendar content, if requested via calendar-data property.
    """

    href: str
    etag: str
    ics_data: str | None = None

    @cached_property
    def normalized_etag(self) -> str:
        """Return the entity tag stripped of surrounding quotes."""
        return self.etag.strip('"')

    @cached_property
    def resource_path(self) -> ResourcePath:
        """Return the strongly-typed ResourcePath object for this resource."""
        return ResourcePath.parse(self.href)

    @cached_property
    def normalized_href(self) -> str:
        """Return the canonical normalized URI href string for this resource."""
        return self.resource_path.canonical

    @cached_property
    def extracted_uid(self) -> str | None:
        """Extract iCalendar UID from raw ics_data using regex."""
        if not self.ics_data:
            return None
        match_obj = re.search(
            r"^UID:(.+)$", self.ics_data, re.MULTILINE | re.IGNORECASE
        )
        return match_obj.group(1).strip() if match_obj else None
