"""Server PROPFIND handlers for root, collection, and resource endpoints.

RFC Reference:
    - RFC 4918 Section 9.1: PROPFIND Method.
    - RFC 4918 Section 13: Multi-Status Response.
"""

import xml.etree.ElementTree as ET
from aiohttp import web

from icaldav.server.handlers.decorators import path_args
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalStore
from icaldav.store.types import LocalStore
from icaldav.xml.namespaces import DAV, qname
from icaldav.xml.propfind.request import parse_propfind_request
from icaldav.xml.propfind.response import append_propfind_response


class PropfindHandler:
    """Handler for WebDAV PROPFIND method queries."""

    def __init__(
        self,
        store: LocalStore,
        principal_store: PrincipalStore | None = None,
    ) -> None:
        self.store = store
        self.principal_store = principal_store or InMemoryPrincipalStore()

    async def handle_root(self, request: web.Request) -> web.Response:
        """Handle PROPFIND request for root '/' autodiscovery."""
        body_bytes = await request.read()
        requested_props = parse_propfind_request(body_bytes)
        principal = await self.principal_store.get_principal(request.get("user"))

        root = ET.Element(qname(DAV, "multistatus"))
        append_propfind_response(
            root,
            "/",
            is_collection=True,
            requested_props=requested_props,
            principal=principal,
        )

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )

    @path_args
    async def handle_collection(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        """Handle PROPFIND request for a calendar collection listing."""
        body_bytes = await request.read()
        requested_props = parse_propfind_request(body_bytes)
        depth = request.headers.get("Depth", "1")
        principal = await self.principal_store.get_principal(request.get("user"))

        root = ET.Element(qname(DAV, "multistatus"))

        coll_href = f"/{collection_id}/"
        append_propfind_response(
            root,
            coll_href,
            is_collection=True,
            requested_props=requested_props,
            principal=principal,
        )

        if depth != "0":
            etags = await self.store.get_etags(collection_id)
            for href, etag in etags.items():
                append_propfind_response(
                    root,
                    href,
                    is_collection=False,
                    etag=etag,
                    requested_props=requested_props,
                )

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )

    @path_args
    async def handle_resource(
        self, request: web.Request, collection_id: str, resource_id: str
    ) -> web.Response:
        """Handle PROPFIND request for a single calendar object resource stat."""
        body_bytes = await request.read()
        requested_props = parse_propfind_request(body_bytes)

        href = f"/{collection_id}/{resource_id}"
        resource = await self.store.get_resource(collection_id, href)
        if not resource:
            return web.Response(status=404, text="Resource Not Found")

        root = ET.Element(qname(DAV, "multistatus"))
        append_propfind_response(
            root,
            href,
            is_collection=False,
            etag=resource.etag,
            requested_props=requested_props,
        )

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )
