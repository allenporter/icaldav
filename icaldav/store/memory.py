"""In-memory implementation of the LocalStore protocol.

Provides fast, transient storage for testing and in-memory calendar caching.
"""

from __future__ import annotations

from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    ResourcePath,
)


class MemoryStore(LocalStore):
    """In-memory store backing calendar collections and resources using Python dictionaries.

    RFC Reference:
        - RFC 4918 / RFC 4791: Transient local storage implementation.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory collections and sync tokens."""
        # CollectionPath -> {ResourcePath -> CalendarResource}
        self._resources: dict[CollectionPath, dict[ResourcePath, CalendarResource]] = {}
        # CollectionPath -> sync_token
        self._tokens: dict[CollectionPath, str] = {}

    async def get_sync_token(self, collection: CollectionPath | str) -> str | None:
        """Retrieve the latest DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        return self._tokens.get(coll)

    async def set_sync_token(
        self, collection: CollectionPath | str, token: str
    ) -> None:
        """Store or update the DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        self._tokens[coll] = token

    async def get_etags(self, collection: CollectionPath | str) -> dict[str, str]:
        """Retrieve a mapping of resource href string to etag for all items in a CollectionPath."""
        coll = CollectionPath.parse(collection)
        resources = self._resources.get(coll, {})
        return {res.href: res.etag for res in resources.values()}

    async def get_resource(self, path: ResourcePath | str) -> CalendarResource | None:
        """Retrieve a single calendar resource by its ResourcePath."""
        res_path = ResourcePath.parse(path)
        collection = self._resources.get(res_path.collection_path, {})
        return collection.get(res_path)

    async def save_resource(self, resource: CalendarResource) -> None:
        """Save or overwrite a calendar object resource in local memory."""
        coll_path = resource.path.collection_path
        if coll_path not in self._resources:
            self._resources[coll_path] = {}

        self._resources[coll_path][resource.path] = resource

    async def delete_resource(self, path: ResourcePath | str) -> bool:
        """Delete a calendar object resource from local memory by its ResourcePath."""
        res_path = ResourcePath.parse(path)
        collection = self._resources.get(res_path.collection_path)
        if collection and res_path in collection:
            del collection[res_path]
            return True
        return False

    async def get_resources(
        self, collection: CollectionPath | str
    ) -> list[CalendarResource]:
        """Retrieve all calendar resources in a CollectionPath."""
        coll = CollectionPath.parse(collection)
        return list(self._resources.get(coll, {}).values())

    async def collection_exists(self, collection: CollectionPath | str) -> bool:
        """Check whether a CollectionPath exists in the store."""
        coll = CollectionPath.parse(collection)
        return coll in self._resources

    async def create_collection(self, collection: CollectionPath | str) -> None:
        """Create a new empty calendar collection."""
        coll = CollectionPath.parse(collection)
        if coll not in self._resources:
            self._resources[coll] = {}
