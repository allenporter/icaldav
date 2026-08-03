"""Server PROPFIND handlers for root, collection, and resource endpoints.

RFC Reference:
    - RFC 4918 Section 9.1: PROPFIND Method.
    - RFC 4918 Section 13: Multi-Status Response.
"""

import xml.etree.ElementTree as ET
from aiohttp import web

from icaldav.server.handlers.decorators import path_args
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalStore
from icaldav.store.types import CollectionPath, LocalStore, ResourcePath
from icaldav.xml.namespaces import DAV, qname
from icaldav.xml.propfind.models import ResourceKind, ResourceTarget
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
        """Handle PROPFIND request for root '/' autodiscovery and principal endpoints."""
        body_bytes = await request.read()
        requested_props = parse_propfind_request(body_bytes)
        principal = await self.principal_store.get_principal(request.get("user"))

        kind = (
            ResourceKind.PRINCIPAL
            if request.path.startswith("/principals/")
            else ResourceKind.ROOT
        )
        target = ResourceTarget(href=request.path, kind=kind, principal=principal)

        root = ET.Element(qname(DAV, "multistatus"))
        append_propfind_response(
            root,
            target,
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
    async def handle_collection(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        """Handle PROPFIND request for a calendar collection listing."""
        body_bytes = await request.read()
        requested_props = parse_propfind_request(body_bytes)
        depth = request.headers.get("Depth", "1")
        principal = await self.principal_store.get_principal(request.get("user"))

        root = ET.Element(qname(DAV, "multistatus"))

        coll_target = ResourceTarget(
            href=f"/{collection_id}/",
            kind=ResourceKind.CALENDAR,
            displayname=collection_id,
            principal=principal,
        )
        append_propfind_response(
            root,
            coll_target,
            requested_props=requested_props,
        )

        if depth != "0":
            coll = CollectionPath.parse(f"/{collection_id}")
            etags = await self.store.get_etags(coll)
            for href, etag in etags.items():
                res_target = ResourceTarget(
                    href=href,
                    kind=ResourceKind.RESOURCE,
                    etag=etag,
                )
                append_propfind_response(
                    root,
                    res_target,
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

        path = ResourcePath.parse(f"/{collection_id}/{resource_id}")
        resource = await self.store.get_resource(path)
        if not resource:
            return web.Response(status=404, text="Resource Not Found")

        target = ResourceTarget(
            href=path.canonical,
            kind=ResourceKind.RESOURCE,
            etag=resource.etag,
        )

        root = ET.Element(qname(DAV, "multistatus"))
        append_propfind_response(
            root,
            target,
            requested_props=requested_props,
        )

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )
