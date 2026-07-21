"""In-memory implementation of the LocalStore protocol.

Provides fast, transient storage for testing and in-memory calendar caching.
"""

from icaldav.store.types import CalendarResource, LocalStore


class MemoryStore(LocalStore):
    """In-memory store backing calendar collections and resources using Python dictionaries.

    RFC Reference:
        - RFC 4918 / RFC 4791: Transient local storage implementation.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory collections and sync tokens."""
        # collection_id -> {href -> CalendarResource}
        self._resources: dict[str, dict[str, CalendarResource]] = {}
        # collection_id -> sync_token
        self._tokens: dict[str, str] = {}

    async def get_sync_token(self, collection_id: str) -> str | None:
        """Retrieve the latest DAV:sync-token for a given calendar collection.

        Args:
            collection_id: Identifier for the calendar collection.

        Returns:
            The sync token string if set, otherwise None.
        """
        return self._tokens.get(collection_id)

    async def set_sync_token(self, collection_id: str, token: str) -> None:
        """Store or update the DAV:sync-token for a given calendar collection.

        Args:
            collection_id: Identifier for the calendar collection.
            token: The new sync token string.
        """
        self._tokens[collection_id] = token

    async def get_etags(self, collection_id: str) -> dict[str, str]:
        """Retrieve a mapping of resource href to etag for all items in a collection.

        Args:
            collection_id: Identifier for the calendar collection.

        Returns:
            A dictionary mapping href to etag.
        """
        collection = self._resources.get(collection_id, {})
        return {href: res.etag for href, res in collection.items()}

    async def get_resource(
        self, collection_id: str, href: str
    ) -> CalendarResource | None:
        """Retrieve a single calendar resource by collection ID and href.

        Args:
            collection_id: Identifier for the calendar collection.
            href: The relative URI path of the resource.

        Returns:
            The CalendarResource if found, or None.
        """
        collection = self._resources.get(collection_id, {})
        return collection.get(href)

    async def save_resource(
        self, collection_id: str, resource: CalendarResource
    ) -> None:
        """Save or overwrite a calendar object resource in local memory.

        Args:
            collection_id: Identifier for the calendar collection.
            resource: The CalendarResource object to persist.
        """
        if collection_id not in self._resources:
            self._resources[collection_id] = {}

        self._resources[collection_id][resource.href] = resource

    async def delete_resource(self, collection_id: str, href: str) -> bool:
        """Delete a calendar object resource from local memory.

        Args:
            collection_id: Identifier for the calendar collection.
            href: Relative URI path of the resource.

        Returns:
            True if deleted, False if resource did not exist.
        """
        collection = self._resources.get(collection_id)
        if collection and href in collection:
            del collection[href]
            return True
        return False
