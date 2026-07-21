"""Server resource handlers for HTTP GET, PUT, and DELETE operations.

RFC Reference:
    - RFC 4918 Section 9.7: DELETE Method.
    - RFC 4791 Section 5.2: Calendar Object Resources (GET).
    - RFC 4791 Section 5.3: Creating/Replacing Calendar Object Resources (PUT).
"""

import hashlib
from aiohttp import web

from icaldav.server.handlers.decorators import path_args
from icaldav.store.types import CalendarResource, LocalStore


class ResourceHandler:
    """Handler for calendar resource CRUD operations (GET, PUT, DELETE)."""

    def __init__(self, store: LocalStore) -> None:
        self.store = store

    @path_args
    async def handle_get(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle GET request to retrieve a raw calendar object resource."""
        href = f"/{collection_id}/{resource_id}"

        resource = await self.store.get_resource(collection_id, href)
        if not resource:
            return web.Response(status=404, text="Resource Not Found")

        clean_etag = resource.etag.strip('"')
        headers = {"ETag": f'"{clean_etag}"'}
        return web.Response(
            status=200,
            text=resource.ics_data,
            content_type="text/calendar",
            charset="utf-8",
            headers=headers,
        )

    @path_args
    async def handle_put(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle PUT request to create or replace an iCalendar object resource file."""
        href = f"/{collection_id}/{resource_id}"

        body_bytes = await request.read()
        ics_content = body_bytes.decode("utf-8")

        etag = hashlib.sha256(body_bytes).hexdigest()[:16]

        existing = await self.store.get_resource(collection_id, href)
        status = 204 if existing else 201

        resource = CalendarResource(
            href=href,
            etag=etag,
            ics_data=ics_content,
        )
        await self.store.save_resource(collection_id, resource)

        headers = {"ETag": f'"{etag}"'}
        return web.Response(status=status, headers=headers)

    @path_args
    async def handle_delete(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle DELETE request to remove a calendar object resource."""
        href = f"/{collection_id}/{resource_id}"

        deleted = await self.store.delete_resource(collection_id, href)
        if not deleted:
            return web.Response(status=404, text="Resource Not Found")

        return web.Response(status=204)
