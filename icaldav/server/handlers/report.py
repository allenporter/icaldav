"""Server REPORT handlers for calendar-query and calendar-multiget.

RFC Reference:
    - RFC 3253 Section 3.6: REPORT Method.
    - RFC 4791 Section 7.8: calendar-query REPORT.
    - RFC 4791 Section 7.9: calendar-multiget REPORT.
"""

from functools import wraps
import logging
from typing import Any, Callable, Coroutine
import xml.etree.ElementTree as ET
from aiohttp import web

from icaldav.filter import matches_comp_filter
from icaldav.store.types import LocalStore
from icaldav.xml.namespaces import strip_ns
from icaldav.xml.report.models import ReportResource
from icaldav.xml.report.request import (
    parse_calendar_multiget,
    parse_calendar_query,
)
from icaldav.xml.report.response import build_report_response

_LOGGER = logging.getLogger(__name__)


def path_args(
    func: Callable[..., Coroutine[Any, Any, web.Response]],
) -> Callable[..., Coroutine[Any, Any, web.Response]]:
    """Decorator unpacking request.match_info directly into handler keyword arguments."""

    @wraps(func)
    async def wrapper(self: Any, request: web.Request) -> web.Response:
        return await func(self, request, **request.match_info)

    return wrapper


class ReportHandler:
    """Handler for CalDAV REPORT method queries."""

    def __init__(self, store: LocalStore) -> None:
        self.store = store

    @path_args
    async def handle_report(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        """Handle REPORT request dispatching to calendar-query or calendar-multiget."""
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
        else:
            return web.Response(status=400, text=f"Unsupported REPORT type: {root_tag}")

    async def _handle_calendar_query(
        self, collection_id: str, body_bytes: bytes
    ) -> web.Response:
        """Evaluate a calendar-query REPORT against stored resources."""
        query = parse_calendar_query(body_bytes)
        all_resources = await self.store.get_resources(collection_id)

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
            resource = await self.store.get_resource(collection_id, href)
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
