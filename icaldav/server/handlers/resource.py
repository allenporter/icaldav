"""Server resource handlers for HTTP GET, PUT, DELETE, COPY, MOVE, and PROPPATCH operations.

RFC Reference:
    - RFC 4918 Section 9.2: PROPPATCH Method.
    - RFC 4918 Section 9.7: DELETE Method.
    - RFC 4918 Section 9.8: COPY Method.
    - RFC 4918 Section 9.9: MOVE Method.
    - RFC 4791 Section 5.2: Calendar Object Resources (GET).
    - RFC 4791 Section 5.3: Creating/Replacing Calendar Object Resources (PUT).
"""

import hashlib

from aiohttp import web
from yarl import URL

from icaldav.server.handlers.decorators import path_args
from icaldav.store.types import (
    CalendarResource,
    LocalStore,
    PropertyTag,
    ResourcePath,
)
from icaldav.xml.namespaces import (
    CALDAV,
    CALSERVER,
    DAV,
    CalDavProp,
    CalServerProp,
    DavProp,
)
from icaldav.xml.proppatch.request import parse_proppatch_request
from icaldav.xml.proppatch.response import build_proppatch_response_xml

PROTECTED_PROPERTIES = {
    (DAV, DavProp.RESOURCETYPE),
    (DAV, DavProp.GETETAG),
    (DAV, DavProp.CURRENT_USER_PRINCIPAL),
    (DAV, DavProp.PRINCIPAL_URL),
    (DAV, DavProp.OWNER),
    (DAV, DavProp.CURRENT_USER_PRIVILEGE_SET),
    (DAV, DavProp.SUPPORTED_REPORT_SET),
    (DAV, DavProp.SYNC_TOKEN),
    (CALDAV, CalDavProp.CALENDAR_HOME_SET),
    (CALDAV, CalDavProp.CALENDAR_USER_ADDRESS_SET),
    (CALDAV, CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET),
    (CALDAV, CalDavProp.MAX_RESOURCE_SIZE),
    (CALSERVER, CalServerProp.GETCTAG),
}


def _normalize_etag(etag: str) -> str:
    """Normalize an HTTP ETag by stripping whitespace, quotes, and weak validator prefix."""
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


def _parse_destination_and_overwrite(
    request: web.Request, src_path: ResourcePath
) -> tuple[ResourcePath | None, bool, web.Response | None]:
    """Parse and validate Destination and Overwrite HTTP headers for COPY and MOVE."""
    dest_header = request.headers.get("Destination")
    if not dest_header:
        return (
            None,
            True,
            web.Response(status=400, text="Bad Request: Missing Destination header"),
        )

    try:
        dest_url = URL(dest_header)
    except Exception:  # noqa: BLE001
        return (
            None,
            True,
            web.Response(status=400, text="Bad Request: Invalid Destination URI"),
        )

    if dest_url.is_absolute():
        req_host = request.host.split(":")[0] if request.host else ""
        if dest_url.host and dest_url.host != req_host:
            return (
                None,
                True,
                web.Response(
                    status=502, text="Bad Gateway: Destination on external server"
                ),
            )

    dest_path = ResourcePath.parse(dest_url.path)
    if src_path.canonical == dest_path.canonical:
        return (
            None,
            True,
            web.Response(
                status=403, text="Forbidden: Source and destination are identical"
            ),
        )

    overwrite_hdr = request.headers.get("Overwrite", "T").upper()
    if overwrite_hdr == "T":
        overwrite = True
    elif overwrite_hdr == "F":
        overwrite = False
    else:
        return (
            None,
            True,
            web.Response(
                status=400, text="Bad Request: Invalid Overwrite header value"
            ),
        )

    return dest_path, overwrite, None


def _validate_proppatch_properties(
    set_props: dict[PropertyTag, str],
    remove_props: list[PropertyTag],
) -> tuple[list[PropertyTag], dict[PropertyTag, int]]:
    """Validate requested properties against protected live properties."""
    failed_props: dict[PropertyTag, int] = {}
    ok_props: list[PropertyTag] = []

    for tag in list(set_props.keys()) + remove_props:
        if (tag.namespace, tag.name) in PROTECTED_PROPERTIES:
            failed_props[tag] = 403
        else:
            ok_props.append(tag)

    return ok_props, failed_props


class ResourceHandler:
    """Handler for calendar resource CRUD and manipulation operations (GET, PUT, DELETE, COPY, MOVE, PROPPATCH)."""

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
        if precond_error := _check_preconditions(request, existing):
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
        if precond_error := _check_preconditions(request, existing):
            return precond_error

        deleted = await self.store.delete_resource(path)
        if not deleted:
            return web.Response(status=404, text="Resource Not Found")

        return web.Response(status=204)

    @path_args
    async def handle_copy(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle COPY request (RFC 4918 §9.8) to duplicate a resource."""
        src_path = ResourcePath.parse(f"/{collection_id}/{resource_id}")
        dest_path, overwrite, err_resp = _parse_destination_and_overwrite(
            request, src_path
        )
        if err_resp is not None or dest_path is None:
            return err_resp or web.Response(status=400)

        src_res = await self.store.get_resource(src_path)
        if src_res is None:
            return web.Response(status=404, text="Source Resource Not Found")
        if precond_error := _check_preconditions(request, src_res):
            return precond_error

        if not await self.store.collection_exists(dest_path.collection_path):
            return web.Response(
                status=409,
                text="Conflict: Destination intermediate collection does not exist",
            )

        dst_res = await self.store.get_resource(dest_path)
        if dst_res is not None and not overwrite:
            return web.Response(
                status=412,
                text="Precondition Failed: Destination resource exists and Overwrite is F",
            )

        overwritten = await self.store.copy_resource(
            src_path, dest_path, overwrite=overwrite
        )
        return web.Response(status=204 if overwritten else 201)

    @path_args
    async def handle_move(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle MOVE request (RFC 4918 §9.9) to relocate a resource."""
        src_path = ResourcePath.parse(f"/{collection_id}/{resource_id}")
        dest_path, overwrite, err_resp = _parse_destination_and_overwrite(
            request, src_path
        )
        if err_resp is not None or dest_path is None:
            return err_resp or web.Response(status=400)

        src_res = await self.store.get_resource(src_path)
        if src_res is None:
            return web.Response(status=404, text="Source Resource Not Found")
        if precond_error := _check_preconditions(request, src_res):
            return precond_error

        if not await self.store.collection_exists(dest_path.collection_path):
            return web.Response(
                status=409,
                text="Conflict: Destination intermediate collection does not exist",
            )

        dst_res = await self.store.get_resource(dest_path)
        if dst_res is not None and not overwrite:
            return web.Response(
                status=412,
                text="Precondition Failed: Destination resource exists and Overwrite is F",
            )

        overwritten = await self.store.move_resource(
            src_path, dest_path, overwrite=overwrite
        )
        return web.Response(status=204 if overwritten else 201)

    @path_args
    async def handle_proppatch(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle PROPPATCH request (RFC 4918 §9.2) to update resource properties."""
        path = ResourcePath.parse(f"/{collection_id}/{resource_id}")
        existing = await self.store.get_resource(path)
        if existing is None:
            return web.Response(status=404, text="Resource Not Found")
        if precond_error := _check_preconditions(request, existing):
            return precond_error

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
                path.canonical, ok_props, failed_props
            )
            return web.Response(
                status=207,
                body=resp_xml,
                content_type="application/xml",
                charset="utf-8",
            )

        await self.store.set_properties(path, set_props, remove_props)
        resp_xml = build_proppatch_response_xml(path.canonical, ok_props)
        return web.Response(
            status=207,
            body=resp_xml,
            content_type="application/xml",
            charset="utf-8",
        )
