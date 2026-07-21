"""Embeddable WebDAV / CalDAV web application router based on aiohttp.web.

RFC References:
  - RFC 4918 Section 9.1: PROPFIND Method.
  - RFC 4918 Section 9.7: DELETE Method.
  - RFC 4918 Section 9.10: OPTIONS Method.
  - RFC 4791 Section 4: Calendar Collections & CalDAV Extensions.
  - RFC 4791 Section 5: Calendar Object Resources.
"""

from functools import wraps
import hashlib
from typing import Any, Callable, Coroutine
import xml.etree.ElementTree as ET
from aiohttp import web

from icaldav.store.types import CalendarResource, LocalStore
from icaldav.xml.namespaces import CALDAV, DAV, qname


def path_args(
    func: Callable[..., Coroutine[Any, Any, web.Response]],
) -> Callable[..., Coroutine[Any, Any, web.Response]]:
    """Decorator unpacking request.match_info directly into handler keyword arguments."""

    @wraps(func)
    async def wrapper(self: Any, request: web.Request) -> web.Response:
        return await func(self, request, **request.match_info)

    return wrapper


class CalDavRouter:
    """Embeddable CalDAV server router producing an aiohttp.web.Application.

    RFC Reference:
        - RFC 4918: WebDAV Specification.
        - RFC 4791: CalDAV Specification.
    """

    def __init__(self, store: LocalStore) -> None:
        """Initialize router with a storage implementation.

        Args:
            store: An implementation of the LocalStore protocol.
        """
        self.store = store

    def create_app(self) -> web.Application:
        """Create and configure an aiohttp.web.Application with WebDAV routes.

        Returns:
            Configured aiohttp.web.Application ready to serve requests or be tested.
        """
        app = web.Application()

        # Collection & Resource Routes
        app.router.add_route("OPTIONS", "/{tail:.*}", self.handle_options)
        app.router.add_route(
            "PROPFIND", "/{collection_id}", self.handle_propfind_collection
        )
        app.router.add_route(
            "PROPFIND",
            "/{collection_id}/{resource_id}",
            self.handle_propfind_resource,
        )
        app.router.add_route("GET", "/{collection_id}/{resource_id}", self.handle_get)
        app.router.add_route("PUT", "/{collection_id}/{resource_id}", self.handle_put)
        app.router.add_route(
            "DELETE", "/{collection_id}/{resource_id}", self.handle_delete
        )

        return app

    async def handle_options(self, request: web.Request) -> web.Response:
        """Handle OPTIONS request advertising WebDAV and CalDAV capabilities.

        RFC Reference:
            - RFC 4918 Section 9.10: OPTIONS Method.
            - RFC 4791 Section 5.1: CalDAV OPTIONS Response.

        Args:
            request: The incoming HTTP request.

        Returns:
            HTTP 200 OK response with DAV capability headers.
        """
        headers = {
            "Allow": "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND",
            "DAV": "1, 2, access-control, calendar-access",
        }
        return web.Response(status=200, headers=headers)

    @path_args
    async def handle_propfind_collection(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        """Handle PROPFIND request for a calendar collection listing.

        PROPFIND Purpose:
            The PROPFIND method (RFC 4918 Section 9.1) acts like `ls` / `dir` + `stat`.
            When issued against a collection path (e.g. `/work/`), it discovers collection properties
            (verifying `DAV:resourcetype` contains `<collection/>` and `<calendar/>`) and lists child items.

        Depth Header Semantics:
            - `Depth: 0`: Returns properties for the target collection itself only.
            - `Depth: 1` (default) or `Depth: infinity`: Returns the collection property node PLUS
              all immediate child calendar resource nodes and their ETags (`DAV:getetag`).
            - Why treating `infinity` as `1` is RFC-compliant: RFC 4791 Section 4.1 specifies that
              Calendar Collections MUST NOT contain nested sub-collections. Because CalDAV calendar
              collections are strictly flat, `Depth: 1` and `Depth: infinity` yield identical results.

        RFC Reference:
            - RFC 4918 Section 9.1: PROPFIND Method.
            - RFC 4791 Section 4.1: Calendar Collections (non-nesting rule).
            - RFC 4918 Section 13: Multi-Status Response.

        Args:
            request: The incoming HTTP request.
            collection_id: Target collection identifier string.

        Returns:
            HTTP 207 Multi-Status XML response.
        """
        depth = request.headers.get("Depth", "1")

        root = ET.Element(
            qname(DAV, "multistatus"),
            attrib={"xmlns:d": DAV, "xmlns:c": CALDAV},
        )

        coll_href = f"/{collection_id}/"
        self._append_response_node(root, coll_href, is_collection=True)

        if depth != "0":
            etags = await self.store.get_etags(collection_id)
            for href, etag in etags.items():
                self._append_response_node(root, href, is_collection=False, etag=etag)

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )

    @path_args
    async def handle_propfind_resource(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle PROPFIND request for a single calendar object resource stat.

        PROPFIND Purpose:
            When issued against an individual file resource (e.g. `/work/event1.ics`), PROPFIND acts
            like a `stat` query. It allows clients to query metadata—such as checking the version
            ETag (`DAV:getetag`) or resource type—without downloading the full `.ics` payload.

        RFC Reference:
            - RFC 4918 Section 9.1: PROPFIND Method.
            - RFC 4918 Section 13: Multi-Status Response.

        Args:
            request: The incoming HTTP request.
            collection_id: Target collection identifier string.
            resource_id: Target resource filename string.

        Returns:
            HTTP 207 Multi-Status XML response or 404 Not Found if resource does not exist.
        """
        href = f"/{collection_id}/{resource_id}"
        resource = await self.store.get_resource(collection_id, href)
        if not resource:
            return web.Response(status=404, text="Resource Not Found")

        root = ET.Element(
            qname(DAV, "multistatus"),
            attrib={"xmlns:d": DAV, "xmlns:c": CALDAV},
        )
        self._append_response_node(root, href, is_collection=False, etag=resource.etag)

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )

    def _append_response_node(
        self,
        root: ET.Element,
        href: str,
        is_collection: bool,
        etag: str | None = None,
    ) -> None:
        """Append a single <DAV:response> element to a <DAV:multistatus> root XML element.

        Appends a response node containing the resource's `href` and a `<DAV:propstat>`
        element grouping its properties under status `HTTP/1.1 200 OK`.

        Args:
            root: Parent `<DAV:multistatus>` ElementTree node.
            href: Relative URI path of the resource or collection.
            is_collection: True if this node represents a calendar collection folder.
            etag: Optional entity tag string for file resources.
        """
        resp = ET.SubElement(root, qname(DAV, "response"))
        href_elem = ET.SubElement(resp, qname(DAV, "href"))
        href_elem.text = href

        propstat = ET.SubElement(resp, qname(DAV, "propstat"))
        prop = ET.SubElement(propstat, qname(DAV, "prop"))

        rt = ET.SubElement(prop, qname(DAV, "resourcetype"))
        if is_collection:
            ET.SubElement(rt, qname(DAV, "collection"))
            ET.SubElement(rt, qname(CALDAV, "calendar"))
        elif etag:
            etag_elem = ET.SubElement(prop, qname(DAV, "getetag"))
            clean_etag = etag.strip('"')
            etag_elem.text = f'"{clean_etag}"'

        status = ET.SubElement(propstat, qname(DAV, "status"))
        status.text = "HTTP/1.1 200 OK"

    @path_args
    async def handle_get(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle GET request to retrieve a raw calendar object resource.

        RFC Reference:
            - RFC 4791 Section 5.2.1: Fetching Calendar Object Resources.

        Args:
            request: The incoming HTTP request.
            collection_id: Target collection identifier string.
            resource_id: Target resource filename string.

        Returns:
            HTTP 200 OK with raw .ics payload or 404 Not Found.
        """
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
        """Handle PUT request to create or replace an iCalendar object resource file.

        A calendar object resource (.ics file) contains iCalendar components such as an
        event (VEVENT), to-do task (VTODO), or journal entry (VJOURNAL). Per RFC 4791
        Section 5.3.1, a PUT request creates or replaces the entire .ics payload stored at the
        target path. This operation performs a complete file overwrite, not a partial update.

        RFC Reference:
            - RFC 4791 Section 5.3.1: Creating or Replacing Calendar Object Resources.

        Args:
            request: The incoming HTTP request.
            collection_id: Target collection identifier string.
            resource_id: Target resource filename string.

        Returns:
            HTTP 201 Created (if new) or 204 No Content (if updated) with ETag header.
        """
        href = f"/{collection_id}/{resource_id}"

        body_bytes = await request.read()
        ics_content = body_bytes.decode("utf-8")

        # Compute deterministic SHA256 ETag
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
        """Handle DELETE request to remove a calendar object resource.

        RFC Reference:
            - RFC 4918 Section 9.7: DELETE Method.

        Args:
            request: The incoming HTTP request.
            collection_id: Target collection identifier string.
            resource_id: Target resource filename string.

        Returns:
            HTTP 204 No Content or 404 Not Found.
        """
        href = f"/{collection_id}/{resource_id}"

        deleted = await self.store.delete_resource(collection_id, href)
        if not deleted:
            return web.Response(status=404, text="Resource Not Found")

        return web.Response(status=204)


def create_app(store: LocalStore) -> web.Application:
    """Helper function to instantiate a CalDavRouter app for a given LocalStore.

    Args:
        store: An implementation of the LocalStore protocol.

    Returns:
        aiohttp.web.Application ready to serve requests.
    """
    return CalDavRouter(store).create_app()
