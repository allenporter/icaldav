"""Server collection handlers for MKCALENDAR operations.

RFC Reference:
    - RFC 4791 Section 5.3.1: Creating Calendar Collections.
"""

from aiohttp import web

from icaldav.server.handlers.decorators import path_args
from icaldav.store.types import LocalStore


class CollectionHandler:
    """Handler for calendar collection operations (MKCALENDAR)."""

    def __init__(self, store: LocalStore) -> None:
        self.store = store

    @path_args
    async def handle_mkcalendar(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        """Handle MKCALENDAR request to create a new calendar collection."""
        if await self.store.collection_exists(collection_id):
            return web.Response(status=405, text="Collection already exists")

        await self.store.create_collection(collection_id)
        return web.Response(status=201)
