"""Server PROPFIND handlers for root, collection, and resource endpoints.

RFC Reference:
    - RFC 4918 Section 9.1: PROPFIND Method.
    - RFC 4918 Section 13: Multi-Status Response.
"""

from aiohttp import web

from icaldav.engine.core import CoreWebDavEngine
from icaldav.engine.models import PropfindQuery
from icaldav.server.handlers.decorators import path_args
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalStore
from icaldav.store.types import LocalStore
from icaldav.xml.propfind.request import parse_propfind_request
from icaldav.xml.propfind.response import build_propfind_response_xml


class PropfindHandler:
    """Handler for WebDAV PROPFIND method queries."""

    def __init__(
        self,
        store: LocalStore,
        principal_store: PrincipalStore | None = None,
    ) -> None:
        self.store = store
        self.principal_store = principal_store or InMemoryPrincipalStore()
        self.engine = CoreWebDavEngine()

    async def handle_root(self, request: web.Request) -> web.Response:
        """Handle PROPFIND request for root '/' autodiscovery and principal endpoints."""
        body_bytes = await request.read()
        requested_props = parse_propfind_request(body_bytes)
        depth_val = request.headers.get("Depth", "0")
        try:
            depth = int(depth_val)
        except ValueError:
            depth = 0

        query = PropfindQuery(
            href=request.path,
            depth=depth,
            requested_props=requested_props,
            user_id=request.get("user"),
        )
        try:
            multistatus = await self.engine.evaluate_propfind(
                self.store, self.principal_store, query
            )
        except FileNotFoundError as err:
            return web.Response(status=404, text=str(err))

        xml_bytes = build_propfind_response_xml(multistatus)
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
        depth_val = request.headers.get("Depth", "1")
        try:
            depth = int(depth_val)
        except ValueError:
            depth = 1

        query = PropfindQuery(
            href=f"/{collection_id}/",
            depth=depth,
            requested_props=requested_props,
            user_id=request.get("user"),
        )
        try:
            multistatus = await self.engine.evaluate_propfind(
                self.store, self.principal_store, query
            )
        except FileNotFoundError as err:
            return web.Response(status=404, text=str(err))

        xml_bytes = build_propfind_response_xml(multistatus)
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
        depth_val = request.headers.get("Depth", "0")
        try:
            depth = int(depth_val)
        except ValueError:
            depth = 0

        query = PropfindQuery(
            href=f"/{collection_id}/{resource_id}",
            depth=depth,
            requested_props=requested_props,
            user_id=request.get("user"),
        )
        try:
            multistatus = await self.engine.evaluate_propfind(
                self.store, self.principal_store, query
            )
        except FileNotFoundError as err:
            return web.Response(status=404, text=str(err))

        xml_bytes = build_propfind_response_xml(multistatus)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )
