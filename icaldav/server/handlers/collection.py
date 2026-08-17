"""Server collection handlers for MKCALENDAR and PROPPATCH operations.

RFC Reference:
    - RFC 4791 Section 5.3.1: Creating Calendar Collections.
    - RFC 4918 Section 9.2: PROPPATCH Method.
"""

from aiohttp import web

from icaldav.server.handlers.decorators import path_args
from icaldav.server.handlers.resource import _validate_proppatch_properties
from icaldav.store.types import CollectionPath, LocalStore
from icaldav.xml.proppatch.request import parse_proppatch_request
from icaldav.xml.proppatch.response import build_proppatch_response_xml


class CollectionHandler:
    """Handler for calendar collection operations (MKCALENDAR, PROPPATCH)."""

    def __init__(self, store: LocalStore) -> None:
        self.store = store

    @path_args
    async def handle_mkcalendar(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        """Handle MKCALENDAR request to create a new calendar collection."""
        coll = CollectionPath.parse(f"/{collection_id}")
        if await self.store.collection_exists(coll):
            return web.Response(status=405, text="Collection already exists")

        await self.store.create_collection(coll)
        return web.Response(status=201)

    @path_args
    async def handle_proppatch(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        """Handle PROPPATCH request (RFC 4918 §9.2) on calendar collections."""
        coll = CollectionPath.parse(f"/{collection_id}")
        if not await self.store.collection_exists(coll):
            return web.Response(status=404, text="Collection Not Found")

        body_bytes = await request.read()
        try:
            set_props, remove_props = parse_proppatch_request(body_bytes)
        except ValueError as err:
            return web.Response(status=400, text=str(err))

        if not set_props and not remove_props:
            return web.Response(status=400, text="Bad Request: Empty propertyupdate")

        ok_props, failed_props = _validate_proppatch_properties(set_props, remove_props)
        if failed_props:
            resp_xml = build_proppatch_response_xml(
                coll.canonical, ok_props, failed_props
            )
            return web.Response(
                status=207,
                body=resp_xml,
                content_type="application/xml",
                charset="utf-8",
            )

        await self.store.set_properties(coll, set_props, remove_props)
        resp_xml = build_proppatch_response_xml(coll.canonical, ok_props)
        return web.Response(
            status=207,
            body=resp_xml,
            content_type="application/xml",
            charset="utf-8",
        )
