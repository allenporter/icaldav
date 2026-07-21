"""Storage interfaces and data structures for icaldav.

RFC References:
  - RFC 4918 Section 14.16: DAV:getetag definition.
  - RFC 6578 Section 3: DAV:sync-token definitions.
"""

from typing import NamedTuple, Protocol


class CalendarResource(NamedTuple):
    """Represents a calendar object resource stored within a collection.

    In WebDAV and CalDAV, URIs (`href`) identify both collection folders and individual event files:
      - Calendar Collection URI (Folder): e.g. `/home/bernard/calendars/work/` (RFC 4791 Section 4.1).
      - Calendar Object Resource URI (File): e.g. `/home/bernard/calendars/work/event1.ics` (RFC 4791 Section 5.2).

    RFC References:
        - RFC 4791 Section 4.1: Calendar Collections.
        - RFC 4791 Section 5.2: Calendar Object Resources.
        - RFC 4918 Section 14.16: DAV:getetag.
    """

    href: str
    """The relative URI path of the resource (e.g. `/home/bernard/calendars/work/event1.ics` or `/home/bernard/calendars/work/`)."""

    etag: str
    """The entity tag representing the current version state of the resource."""

    ics_data: str
    """The raw RFC 5545 iCalendar content."""

    uid: str | None = None
    """The optional VEVENT/VTODO UID extracted from the iCalendar content."""


class LocalStore(Protocol):
    """Abstract protocol for local calendar resource and sync token persistence.

    Store Granularity & Architecture:
      - A single `LocalStore` instance represents the local database for an application or engine.
      - A store holds multiple **Calendar Collections** (isolated by `collection_id`, e.g., `"work"`, `"personal"`).
      - Each collection tracks its own incremental sync state (`sync_token`) and resources (`CalendarResource`).
      - Implementations include `MemoryStore` (in-memory caching/testing) and `SQLiteStore` (persistent disk storage).
    """

    async def get_sync_token(self, collection_id: str) -> str | None:
        """Retrieve the latest DAV:sync-token for a given calendar collection.

        RFC Reference:
            - RFC 6578 Section 3: The DAV:sync-token Property.

        Args:
            collection_id: Identifier for the calendar collection.

        Returns:
            The current sync token string, or None if no token exists.
        """
        ...

    async def set_sync_token(self, collection_id: str, token: str) -> None:
        """Store or update the DAV:sync-token for a given calendar collection.

        RFC Reference:
            - RFC 6578 Section 3: The DAV:sync-token Property.

        Args:
            collection_id: Identifier for the calendar collection.
            token: The new sync token string.
        """
        ...

    async def get_etags(self, collection_id: str) -> dict[str, str]:
        """Retrieve a mapping of resource href to etag for all items in a collection.

        RFC Reference:
            - RFC 4918 Section 14.16: DAV:getetag.

        Args:
            collection_id: Identifier for the calendar collection.

        Returns:
            A dictionary mapping resource href string to etag string.
        """
        ...

    async def get_resource(
        self, collection_id: str, href: str
    ) -> CalendarResource | None:
        """Retrieve a single calendar resource by collection ID and href.

        RFC Reference:
            - RFC 4791 Section 5.2: Calendar Object Resources.

        Args:
            collection_id: Identifier for the calendar collection.
            href: The relative URI path of the resource.

        Returns:
            The CalendarResource object if found, or None.
        """
        ...

    async def save_resource(
        self, collection_id: str, resource: CalendarResource
    ) -> None:
        """Save or overwrite a calendar object resource in local storage.

        RFC Reference:
            - RFC 4791 Section 5.3.1: Creating Calendar Object Resources.

        Args:
            collection_id: Identifier for the calendar collection.
            resource: The CalendarResource object to persist.
        """
        ...

    async def delete_resource(self, collection_id: str, href: str) -> bool:
        """Delete a calendar object resource from local storage.

        RFC Reference:
            - RFC 4918 Section 9.7: DELETE Method.

        Args:
            collection_id: Identifier for the calendar collection.
            href: The relative URI path of the resource.

        Returns:
            True if the resource was deleted, False if it did not exist.
        """
        ...

    async def get_resources(self, collection_id: str) -> list[CalendarResource]:
        """Retrieve all calendar resources in a collection.

        Used by calendar-query REPORT (RFC 4791 §7.8) to load all resources
        for server-side filtering by component type and time range.

        Args:
            collection_id: Identifier for the calendar collection.

        Returns:
            List of all CalendarResource objects in the collection.
        """
        ...

    async def collection_exists(self, collection_id: str) -> bool:
        """Check whether a calendar collection exists in the store.

        Used by MKCALENDAR (RFC 4791 §5.3.1) to prevent duplicate creation,
        and by REPORT handlers to validate the target collection.

        Args:
            collection_id: Identifier for the calendar collection.

        Returns:
            True if the collection exists, False otherwise.
        """
        ...

    async def create_collection(self, collection_id: str) -> None:
        """Create a new empty calendar collection.

        Called by MKCALENDAR (RFC 4791 §5.3.1) to provision a new calendar
        collection with resource types DAV:collection and CALDAV:calendar.

        Args:
            collection_id: Identifier for the new calendar collection.
        """
        ...
