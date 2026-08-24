"""In-memory implementation of the LocalStore protocol.

Provides fast, transient storage for testing and in-memory calendar caching.
"""

from __future__ import annotations

from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    PropertyTag,
    ResourcePath,
    SyncChanges,
    SyncToken,
)


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
        # path string -> {PropertyTag -> str}
        self._properties: dict[str, dict[PropertyTag, str]] = {}

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
            return SyncToken.from_sequence(counter).uri
        return None

    async def set_sync_token(
        self, collection: CollectionPath | str, token: str
    ) -> None:
        """Store or update the DAV:sync-token for a given CollectionPath."""
        coll = CollectionPath.parse(collection)
        st = SyncToken.parse(token)
        self._token_counters[coll] = st.sequence
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

    def _initial_sync_changes(
        self,
        coll: CollectionPath,
        curr_token_str: str,
        limit: int | None,
    ) -> SyncChanges:
        tokens = self._resource_tokens.get(coll, {})
        coll_resources = self._resources.get(coll, {})
        sorted_res = sorted(
            coll_resources.values(),
            key=lambda r: (tokens.get(r.path, 0), r.path.canonical),
        )
        if limit is not None and limit > 0 and len(sorted_res) > limit:
            selected_res = sorted_res[:limit]
            last_token_id = tokens.get(selected_res[-1].path, 0)
            page_token = SyncToken.from_sequence(last_token_id).uri
            return SyncChanges(
                sync_token=page_token,
                changed=selected_res,
                deleted_hrefs=[],
                has_more=True,
            )
        return SyncChanges(
            sync_token=curr_token_str,
            changed=sorted_res,
            deleted_hrefs=[],
            has_more=False,
        )

    def _delta_sync_changes(
        self,
        coll: CollectionPath,
        token_num: int,
        curr_token_str: str,
        limit: int | None,
    ) -> SyncChanges:
        tokens = self._resource_tokens.get(coll, {})
        coll_resources = self._resources.get(coll, {})
        changed_res = [
            (res, tokens.get(r_path, 0))
            for r_path, res in coll_resources.items()
            if tokens.get(r_path, 0) > token_num
        ]
        changed_paths = {res.path.canonical for res, _ in changed_res}
        tomb_list = self._tombstones.get(coll, [])
        deleted_items = [
            (p_str, t_num)
            for p_str, t_num in tomb_list
            if t_num > token_num and p_str not in changed_paths
        ]

        all_changes: list[tuple[str, CalendarResource | str, int]] = []
        for res, t_id in changed_res:
            all_changes.append(("changed", res, t_id))
        for p_str, t_id in deleted_items:
            all_changes.append(("deleted", p_str, t_id))

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

        changed_out: list[CalendarResource] = [
            item[1] for item in selected if isinstance(item[1], CalendarResource)
        ]
        deleted_out: list[str] = [
            item[1] for item in selected if isinstance(item[1], str)
        ]

        return SyncChanges(
            sync_token=page_token,
            changed=changed_out,
            deleted_hrefs=deleted_out,
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
        curr_counter = self._token_counters.get(coll, 0)
        curr_token_str = self._custom_tokens.get(
            coll, SyncToken.from_sequence(curr_counter).uri
        )

        st = SyncToken.parse(sync_token)
        if st.sequence == 0:
            return self._initial_sync_changes(coll, curr_token_str, limit)
        return self._delta_sync_changes(coll, st.sequence, curr_token_str, limit)

    async def copy_resource(
        self,
        source: ResourcePath | str,
        destination: ResourcePath | str,
        overwrite: bool = True,
    ) -> bool:
        """Copy a calendar resource from source to destination path."""
        src_path = ResourcePath.parse(source)
        dst_path = ResourcePath.parse(destination)

        src_res = await self.get_resource(src_path)
        if src_res is None:
            raise FileNotFoundError(f"Source resource not found: {src_path}")

        if not await self.collection_exists(dst_path.collection_path):
            raise FileNotFoundError(
                f"Destination collection does not exist: {dst_path.collection_path}"
            )

        existing_dst = await self.get_resource(dst_path)
        if existing_dst is not None:
            if not overwrite:
                raise FileExistsError(
                    f"Destination resource already exists: {dst_path}"
                )
            overwritten = True
        else:
            overwritten = False

        new_res = CalendarResource(
            path=dst_path,
            etag=src_res.etag,
            ics_data=src_res.ics_data,
            uid=src_res.uid,
        )
        await self.save_resource(new_res)

        # Copy custom dead properties if any
        if src_path.canonical in self._properties:
            self._properties[dst_path.canonical] = dict(
                self._properties[src_path.canonical]
            )

        return overwritten

    async def move_resource(
        self,
        source: ResourcePath | str,
        destination: ResourcePath | str,
        overwrite: bool = True,
    ) -> bool:
        """Move a calendar resource from source to destination path."""
        src_path = ResourcePath.parse(source)
        dst_path = ResourcePath.parse(destination)

        overwritten = await self.copy_resource(src_path, dst_path, overwrite=overwrite)
        await self.delete_resource(src_path)

        if src_path.canonical in self._properties:
            props = self._properties.pop(src_path.canonical, {})
            self._properties[dst_path.canonical] = props

        return overwritten

    async def get_properties(
        self, path: CollectionPath | ResourcePath | str
    ) -> dict[PropertyTag, str]:
        """Retrieve custom dead properties for a collection or resource path."""
        p_str = str(path)
        return dict(self._properties.get(p_str, {}))

    async def set_properties(
        self,
        path: CollectionPath | ResourcePath | str,
        set_props: dict[PropertyTag, str],
        remove_props: list[PropertyTag] | None = None,
    ) -> None:
        """Set or remove custom dead properties on a collection or resource path."""
        p_str = str(path)
        if p_str not in self._properties:
            self._properties[p_str] = {}

        for k, v in set_props.items():
            self._properties[p_str][k] = v

        for k in remove_props or []:
            self._properties[p_str].pop(k, None)
