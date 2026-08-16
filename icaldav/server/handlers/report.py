"""Server REPORT handlers for calendar-query and calendar-multiget.

RFC Reference:
    - RFC 3253 Section 3.6: REPORT Method.
    - RFC 4791 Section 7.8: calendar-query REPORT.
    - RFC 4791 Section 7.9: calendar-multiget REPORT.
"""

from aiohttp import web

from icaldav.engine.core import CoreWebDavEngine
from icaldav.engine.models import PrincipalSearchQuery
from icaldav.server.handlers.decorators import path_args
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalStore
from icaldav.store.types import CollectionPath, LocalStore
from icaldav.xml.propfind.response import build_propfind_response_xml
from icaldav.xml.report.request import (
    parse_calendar_multiget,
    parse_calendar_query,
    parse_principal_property_search,
    parse_report_root_tag,
    parse_sync_collection,
)
from icaldav.xml.report.response import build_report_response


class ReportHandler:
    """Handler for CalDAV REPORT method queries."""

    def __init__(
        self,
        store: LocalStore,
        principal_store: PrincipalStore | None = None,
    ) -> None:
        self.store = store
        self.principal_store = principal_store or InMemoryPrincipalStore()
        self.engine = CoreWebDavEngine()

    @path_args
    async def handle_report(
        self, request: web.Request, collection_id: str = ""
    ) -> web.Response:
        """Handle REPORT request dispatching to calendar-query, calendar-multiget, or principal-property-search."""
        body_bytes = await request.read()
        if not body_bytes:
            return web.Response(status=400, text="REPORT requires XML body")

        root_tag = parse_report_root_tag(body_bytes)
        if not root_tag:
            return web.Response(status=400, text="Invalid XML")

        if root_tag == "calendar-query":
            return await self._handle_calendar_query(collection_id, body_bytes)
        elif root_tag == "calendar-multiget":
            return await self._handle_calendar_multiget(collection_id, body_bytes)
        elif root_tag == "principal-property-search":
            return await self._handle_principal_property_search(request, body_bytes)
        elif root_tag == "sync-collection":
            return await self._handle_sync_collection(collection_id, body_bytes)
        else:
            return web.Response(status=400, text=f"Unsupported REPORT type: {root_tag}")

    async def _handle_sync_collection(
        self, collection_id: str, body_bytes: bytes
    ) -> web.Response:
        """Evaluate a sync-collection REPORT (RFC 6578)."""
        query = parse_sync_collection(body_bytes)
        coll = CollectionPath.parse(f"/{collection_id}" if collection_id else "/")
        result = await self.engine.evaluate_sync_collection(self.store, coll, query)
        xml_bytes = build_report_response(result)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )

    async def _handle_principal_property_search(
        self, request: web.Request, body_bytes: bytes
    ) -> web.Response:
        """Evaluate a principal-property-search REPORT (RFC 3744 §9.4)."""
        query = parse_principal_property_search(body_bytes)
        query = PrincipalSearchQuery(
            criteria=query.criteria,
            props=query.props,
            user_id=request.get("user"),
        )
        multistatus = await self.engine.evaluate_principal_search(
            self.principal_store, query
        )
        xml_bytes = build_propfind_response_xml(multistatus)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )

    async def _handle_calendar_query(
        self, collection_id: str, body_bytes: bytes
    ) -> web.Response:
        """Evaluate a calendar-query REPORT against stored resources."""
        query = parse_calendar_query(body_bytes)
        coll = CollectionPath.parse(f"/{collection_id}" if collection_id else "/")
        result = await self.engine.evaluate_calendar_query(self.store, coll, query)
        xml_bytes = build_report_response(result)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )

    async def _handle_calendar_multiget(
        self, collection_id: str, body_bytes: bytes
    ) -> web.Response:
        """Resolve specific resource hrefs for a calendar-multiget REPORT."""
        query = parse_calendar_multiget(body_bytes)
        result = await self.engine.evaluate_calendar_multiget(self.store, query)
        xml_bytes = build_report_response(result)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )
