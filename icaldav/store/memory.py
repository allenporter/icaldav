"""In-memory implementation of the LocalStore protocol.

Provides fast, transient storage for testing and in-memory calendar caching.
"""

from __future__ import annotations

import re

from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    ResourcePath,
    SyncChanges,
)


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


class MemoryStore(LocalStore):
    """In-memory store backing calendar collections and resources using Python dictionaries.

    RFC Reference:
        - RFC 4918 / RFC 4791: Transient local storage implementation.
        - RFC 6578: In-memory tombstone and sync token tracking.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory collections, sync tokens, and tombstones."""
        # CollectionPath -> {ResourcePath -> CalendarResource}
        self._resources: dict[CollectionPath, dict[ResourcePath, CalendarResource]] = {}
        # CollectionPath -> {ResourcePath -> token_id}
        self._resource_tokens: dict[CollectionPath, dict[ResourcePath, int]] = {}
        # CollectionPath -> list[(path_str, token_id)]
        self._tombstones: dict[CollectionPath, list[tuple[str, int]]] = {}
        # CollectionPath -> int counter
        self._token_counters: dict[CollectionPath, int] = {}
        # CollectionPath -> custom sync_token string
        self._custom_tokens: dict[CollectionPath, str] = {}

    def _next_counter(self, coll: CollectionPath) -> int:
        curr = self._token_counters.get(coll, 0) + 1
        self._token_counters[coll] = curr
        self._custom_tokens.pop(coll, None)
        return curr

    async def get_sync_token(self, collection: CollectionPath | str) -> str | None:
        """Retrieve the latest DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        if coll in self._custom_tokens:
            return self._custom_tokens[coll]
        counter = self._token_counters.get(coll)
        if counter is not None:
            return f"data:,{counter}"
        return None

    async def set_sync_token(
        self, collection: CollectionPath | str, token: str
    ) -> None:
        """Store or update the DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        self._token_counters[coll] = _extract_token_int(token)
        self._custom_tokens[coll] = token

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
            self._resource_tokens[coll_path] = {}

        counter = self._next_counter(coll_path)
        self._resources[coll_path][resource.path] = resource
        self._resource_tokens[coll_path][resource.path] = counter

    async def delete_resource(self, path: ResourcePath | str) -> bool:
        """Delete a calendar object resource from local memory by its ResourcePath."""
        res_path = ResourcePath.parse(path)
        coll_path = res_path.collection_path
        collection = self._resources.get(coll_path)
        if collection and res_path in collection:
            del collection[res_path]
            if (
                coll_path in self._resource_tokens
                and res_path in self._resource_tokens[coll_path]
            ):
                del self._resource_tokens[coll_path][res_path]

            counter = self._next_counter(coll_path)
            if coll_path not in self._tombstones:
                self._tombstones[coll_path] = []
            self._tombstones[coll_path].append((res_path.canonical, counter))
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
        return (
            coll in self._resources
            or coll in self._token_counters
            or coll in self._custom_tokens
        )

    async def create_collection(self, collection: CollectionPath | str) -> None:
        """Create a new empty calendar collection."""
        coll = CollectionPath.parse(collection)
        if coll not in self._resources:
            self._resources[coll] = {}
            self._resource_tokens[coll] = {}
            self._token_counters[coll] = 0

    async def get_changes_since(
        self,
        collection: CollectionPath | str,
        sync_token: str | None = None,
        limit: int | None = None,
    ) -> SyncChanges:
        """Retrieve modified and deleted resources in a CollectionPath since a sync token."""
        coll = CollectionPath.parse(collection)
        curr_counter = self._token_counters.get(coll, 0)
        curr_token_str = self._custom_tokens.get(coll, f"data:,{curr_counter}")

        token_num = _extract_token_int(sync_token)

        if token_num == 0:
            # Initial sync
            resources = list(self._resources.get(coll, {}).values())
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

        # Delta sync: changed items
        tokens = self._resource_tokens.get(coll, {})
        coll_resources = self._resources.get(coll, {})
        changed_res = [
            res
            for r_path, res in coll_resources.items()
            if tokens.get(r_path, 0) > token_num
        ]

        # Delta sync: tombstones
        tomb_list = self._tombstones.get(coll, [])
        changed_paths = {r.path.canonical for r in changed_res}
        deleted_hrefs = [
            p_str
            for p_str, t_num in tomb_list
            if t_num > token_num and p_str not in changed_paths
        ]

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
