"""Server resource handlers for HTTP GET, PUT, and DELETE operations.

RFC Reference:
    - RFC 4918 Section 9.7: DELETE Method.
    - RFC 4791 Section 5.2: Calendar Object Resources (GET).
    - RFC 4791 Section 5.3: Creating/Replacing Calendar Object Resources (PUT).
"""

import hashlib

from aiohttp import web

from icaldav.server.handlers.decorators import path_args
from icaldav.store.types import CalendarResource, LocalStore, ResourcePath


def _normalize_etag(etag: str) -> str:
    cleaned = etag.strip()
    cleaned = cleaned.removeprefix("W/")
    return cleaned.strip('"')


def _check_if_match(
    if_match: str, existing: CalendarResource | None
) -> web.Response | None:
    tags = [t.strip() for t in if_match.split(",")]
    if "*" in tags:
        if existing is None:
            return web.Response(
                status=412, text="Precondition Failed: Resource does not exist"
            )
        return None

    if existing is None:
        return web.Response(
            status=412, text="Precondition Failed: Resource does not exist"
        )

    existing_clean = _normalize_etag(existing.etag)
    matched_tags = {_normalize_etag(t) for t in tags}
    if existing_clean not in matched_tags:
        return web.Response(status=412, text="Precondition Failed: ETag mismatch")
    return None


def _check_if_none_match(
    if_none_match: str, existing: CalendarResource | None
) -> web.Response | None:
    tags = [t.strip() for t in if_none_match.split(",")]
    if "*" in tags:
        if existing is not None:
            return web.Response(
                status=412, text="Precondition Failed: Resource already exists"
            )
        return None

    if existing is not None:
        existing_clean = _normalize_etag(existing.etag)
        matched_tags = {_normalize_etag(t) for t in tags}
        if existing_clean in matched_tags:
            return web.Response(status=412, text="Precondition Failed: ETag match")
    return None


def _check_preconditions(
    request: web.Request, existing: CalendarResource | None
) -> web.Response | None:
    if_match = request.headers.get("If-Match")
    if if_match is not None:
        resp = _check_if_match(if_match, existing)
        if resp is not None:
            return resp

    if_none_match = request.headers.get("If-None-Match")
    if if_none_match is not None:
        resp = _check_if_none_match(if_none_match, existing)
        if resp is not None:
            return resp

    return None


class ResourceHandler:
    """Handler for calendar resource CRUD operations (GET, PUT, DELETE)."""

    def __init__(self, store: LocalStore) -> None:
        self.store = store

    @path_args
    async def handle_get(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle GET request to retrieve a raw calendar object resource."""
        path = ResourcePath.parse(f"/{collection_id}/{resource_id}")

        resource = await self.store.get_resource(path)
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
        path = ResourcePath.parse(f"/{collection_id}/{resource_id}")

        existing = await self.store.get_resource(path)
        precond_error = _check_preconditions(request, existing)
        if precond_error is not None:
            return precond_error

        body_bytes = await request.read()
        ics_content = body_bytes.decode("utf-8")

        etag = hashlib.sha256(body_bytes).hexdigest()[:16]
        status = 204 if existing else 201

        resource = CalendarResource(
            path=path,
            etag=etag,
            ics_data=ics_content,
        )
        await self.store.save_resource(resource)

        headers = {"ETag": f'"{etag}"'}
        return web.Response(status=status, headers=headers)

    @path_args
    async def handle_delete(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle DELETE request to remove a calendar object resource."""
        path = ResourcePath.parse(f"/{collection_id}/{resource_id}")

        existing = await self.store.get_resource(path)
        precond_error = _check_preconditions(request, existing)
        if precond_error is not None:
            return precond_error

        deleted = await self.store.delete_resource(path)
        if not deleted:
            return web.Response(status=404, text="Resource Not Found")

        return web.Response(status=204)
