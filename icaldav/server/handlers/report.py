"""Server REPORT handlers for calendar-query and calendar-multiget.

RFC Reference:
    - RFC 3253 Section 3.6: REPORT Method.
    - RFC 4791 Section 7.8: calendar-query REPORT.
    - RFC 4791 Section 7.9: calendar-multiget REPORT.
"""

import logging
import xml.etree.ElementTree as ET
from aiohttp import web

from icaldav.filter import matches_comp_filter
from icaldav.server.handlers.decorators import path_args
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalStore
from icaldav.store.types import CollectionPath, LocalStore, ResourcePath

from icaldav.xml.namespaces import DAV, qname, strip_ns
from icaldav.xml.propfind.models import ResourceKind, ResourceTarget
from icaldav.xml.propfind.response import append_propfind_response
from icaldav.xml.report.models import ReportResource
from icaldav.xml.report.request import (
    parse_calendar_multiget,
    parse_calendar_query,
    parse_principal_property_search,
    parse_sync_collection,
)
from icaldav.xml.report.response import build_report_response

_LOGGER = logging.getLogger(__name__)


class ReportHandler:
    """Handler for CalDAV REPORT method queries."""

    def __init__(
        self,
        store: LocalStore,
        principal_store: PrincipalStore | None = None,
    ) -> None:
        self.store = store
        self.principal_store = principal_store or InMemoryPrincipalStore()

    @path_args
    async def handle_report(
        self, request: web.Request, collection_id: str = ""
    ) -> web.Response:
        """Handle REPORT request dispatching to calendar-query, calendar-multiget, or principal-property-search."""
        body_bytes = await request.read()
        if not body_bytes:
            return web.Response(status=400, text="REPORT requires XML body")

        try:
            root = ET.fromstring(body_bytes)
        except ET.ParseError:
            _LOGGER.debug("Failed to parse REPORT XML body", exc_info=True)
            return web.Response(status=400, text="Invalid XML")

        root_tag = strip_ns(root.tag)

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
        req = parse_sync_collection(body_bytes)
        coll = CollectionPath.parse(f"/{collection_id}" if collection_id else "/")
        resources = await self.store.get_resources(coll)
        matched = [
            ReportResource(href=res.href, etag=res.etag, ics_data=res.ics_data)
            for res in resources
        ]
        if req.limit is not None and req.limit > 0:
            matched = matched[: req.limit]

        xml_bytes = build_report_response(matched)
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
        search_req = parse_principal_property_search(body_bytes)

        principals = []
        match_terms = [c.match for c in search_req.criteria if c.match]
        if match_terms:
            for term in match_terms:
                found = await self.principal_store.search_principals(term)
                for p in found:
                    if p not in principals:
                        principals.append(p)
        else:
            principal = await self.principal_store.get_principal(request.get("user"))
            principals.append(principal)

        root = ET.Element(qname(DAV, "multistatus"))
        for p in principals:
            target = ResourceTarget(
                href=p.principal_path,
                kind=ResourceKind.PRINCIPAL,
                principal=p,
            )
            append_propfind_response(root, target)

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
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
        all_resources = await self.store.get_resources(coll)

        include_data = "calendar-data" in query.props
        matched = []
        for resource in all_resources:
            if matches_comp_filter(resource.ics_data, query.comp_filter):
                matched.append(
                    ReportResource(
                        href=resource.href,
                        etag=resource.etag,
                        ics_data=resource.ics_data if include_data else None,
                    )
                )

        xml_bytes = build_report_response(matched)
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
        multiget = parse_calendar_multiget(body_bytes)
        include_data = "calendar-data" in multiget.props

        found = []
        missing = []
        for href in multiget.hrefs:
            resource = await self.store.get_resource(ResourcePath.parse(href))
            if resource:
                found.append(
                    ReportResource(
                        href=resource.href,
                        etag=resource.etag,
                        ics_data=resource.ics_data if include_data else None,
                    )
                )
            else:
                missing.append(href)

        xml_bytes = build_report_response(found, missing_hrefs=missing)
        return web.Response(
            status=207,
            body=xml_bytes,
            content_type="application/xml",
            charset="utf-8",
        )
