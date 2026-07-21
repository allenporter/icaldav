"""Server collection handlers for MKCALENDAR operations.

RFC Reference:
    - RFC 4791 Section 5.3.1: Creating Calendar Collections.
"""

from functools import wraps
from typing import Any, Callable, Coroutine
from aiohttp import web

from icaldav.store.types import LocalStore


def path_args(
    func: Callable[..., Coroutine[Any, Any, web.Response]],
) -> Callable[..., Coroutine[Any, Any, web.Response]]:
    """Decorator unpacking request.match_info directly into handler keyword arguments."""

    @wraps(func)
    async def wrapper(self: Any, request: web.Request) -> web.Response:
        return await func(self, request, **request.match_info)

    return wrapper


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
