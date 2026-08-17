"""HTTP Client Transport for WebDAV and CalDAV operations.

RFC References:
  - RFC 4918 Section 9.1: PROPFIND Method.
  - RFC 4918 Section 9.7: DELETE Method.
  - RFC 4791 Section 5.2: Calendar Object Resources (GET / PUT).
  - RFC 4791 Section 7.8: calendar-query REPORT.
  - RFC 4791 Section 7.9: calendar-multiget REPORT.
  - RFC 7617: HTTP Basic Authentication.
  - RFC 6750: OAuth 2.0 Bearer Token Usage.
  - RFC 7235 Section 4.1: WWW-Authenticate Header Field.
"""

import warnings
from typing import Self

import aiohttp

from icaldav.client.auth import AuthProfile
from icaldav.client.exceptions import CalDavAuthError
from icaldav.store.types import ReportResource
from icaldav.xml.propfind.models import PropfindItem
from icaldav.xml.propfind.request import build_propfind_xml
from icaldav.xml.propfind.response import parse_multistatus_xml
from icaldav.xml.report.request import (
    build_calendar_multiget_xml,
    build_calendar_query_xml,
    build_principal_property_search_xml,
    build_sync_collection_xml,
)
from icaldav.xml.report.response import (
    parse_report_response,
    parse_sync_collection_response,
)


class CalDavClient:
    """Asynchronous client for interacting with WebDAV / CalDAV servers using aiohttp.

    RFC References:
        - RFC 4918: WebDAV Core Protocols.
        - RFC 4791: CalDAV Extensions.
        - RFC 7617: HTTP Basic Authentication.
        - RFC 6750: Bearer Tokens.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        auth_profile: AuthProfile | None = None,
    ) -> None:
        """Initialize CalDavClient with optional session and auth profile.

        Args:
            session: Optional existing aiohttp.ClientSession. If None, an internal session is created.
            auth_profile: Optional AuthProfile managing credentials and OAuth auto-refresh.
        """
        self._session = session
        self._owned_session = session is None
        self.auth_profile = auth_profile
        self._active_token: str | None = auth_profile.token if auth_profile else None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Retrieve active ClientSession, obtaining configured session kwargs from auth_profile."""
        if self.auth_profile and self.auth_profile.auth_type == "oauth":
            fresh_token = await self.auth_profile.ensure_fresh_token()
            if fresh_token and fresh_token != self._active_token:
                self._active_token = fresh_token
                if self._session is not None and not self._session.closed:
                    await self._session.close()
                self._session = None

        if self._session is None or self._session.closed:
            kwargs = (
                await self.auth_profile.get_session_kwargs()
                if self.auth_profile
                else {}
            )
            self._session = aiohttp.ClientSession(**kwargs)
            self._owned_session = True
        return self._session

    def _warn_insecure_auth(self, url: str) -> None:
        """Emit a warning if credentials are being sent over non-HTTPS."""
        if (
            self.auth_profile
            and not url.startswith("https://")
            and (self.auth_profile.basic_auth or self.auth_profile.token)
        ):
            warnings.warn(
                f"Sending credentials over insecure HTTP connection to {url}. "
                "Use HTTPS to protect credentials in transit.",
                stacklevel=3,
            )

    def _check_response(self, resp: aiohttp.ClientResponse) -> None:
        """Inspect HTTP response status and raise CalDavAuthError on 401/403 with WWW-Authenticate.

        Args:
            resp: The aiohttp.ClientResponse object.

        Raises:
            CalDavAuthError: If HTTP status is 401 or 403.
            aiohttp.ClientResponseError: For other 4xx/5xx HTTP status codes.
        """
        if resp.status in (401, 403):
            challenges: list[str] = []
            if "WWW-Authenticate" in resp.headers:
                challenges = resp.headers.getall("WWW-Authenticate")
            raise CalDavAuthError(
                url=str(resp.url),
                status=resp.status,
                challenges=challenges,
            )
        resp.raise_for_status()

    async def close(self) -> None:
        """Close the underlying ClientSession if owned by this client instance."""
        if self._owned_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def propfind(
        self, url: str, depth: int = 1, props: list[str] | None = None
    ) -> list[PropfindItem]:
        """Perform a WebDAV PROPFIND request to query collection or resource properties.

        RFC Reference:
            - RFC 4918 Section 9.1: PROPFIND Method.
            - RFC 4918 Section 13: Multi-Status Response.

        Args:
            url: Full or relative target URI path.
            depth: Depth header value (0 for target resource only, 1 for collection children).
            props: Optional list of property names to request.

        Returns:
            List of parsed PropfindItem objects.

        Raises:
            CalDavAuthError: If authentication is required or rejected (HTTP 401/403).
            aiohttp.ClientResponseError: If the server returns another non-207 status code.
        """
        session = await self._get_session()
        self._warn_insecure_auth(url)
        body = build_propfind_xml(props or ["resourcetype", "getetag", "displayname"])
        headers = {
            "Depth": str(depth),
            "Content-Type": "application/xml; charset=utf-8",
        }

        async with session.request("PROPFIND", url, data=body, headers=headers) as resp:
            self._check_response(resp)
            content = await resp.read()
            return parse_multistatus_xml(content)

    async def get_resource(self, url: str) -> tuple[str, str]:
        """Fetch raw iCalendar content and etag from a calendar resource URL via HTTP GET.

        RFC Reference:
            - RFC 4791 Section 5.2.1: Fetching Calendar Object Resources.

        Args:
            url: Target resource URI path.

        Returns:
            Tuple of (ics_content_string, etag_string).

        Raises:
            CalDavAuthError: If authentication is required or rejected (HTTP 401/403).
            aiohttp.ClientResponseError: If the HTTP response status is not 200 OK.
        """
        session = await self._get_session()
        self._warn_insecure_auth(url)
        headers = {"Accept": "text/calendar, text/plain, */*"}

        async with session.get(url, headers=headers) as resp:
            self._check_response(resp)
            ics_text = await resp.text()
            etag = resp.headers.get("ETag", "").strip('"')
            return ics_text, etag

    async def put_resource(
        self, url: str, ics_content: str, etag: str | None = None
    ) -> str:
        """Create or update a calendar object resource via HTTP PUT.

        RFC Reference:
            - RFC 4791 Section 5.3.1: Creating Calendar Object Resources.

        Args:
            url: Target resource URI path.
            ics_content: Raw iCalendar payload string.
            etag: Optional ETag for conditional If-Match precondition checks.

        Returns:
            The server-returned or assigned ETag string.

        Raises:
            CalDavAuthError: If authentication is required or rejected (HTTP 401/403).
            aiohttp.ClientResponseError: If the server rejects the request.
        """
        session = await self._get_session()
        self._warn_insecure_auth(url)
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            headers["If-Match"] = f'"{etag}"' if not etag.startswith('"') else etag

        async with session.put(
            url, data=ics_content.encode("utf-8"), headers=headers
        ) as resp:
            self._check_response(resp)
            resp_etag = resp.headers.get("ETag", "").strip('"')
            return resp_etag

    async def delete_resource(self, url: str, etag: str | None = None) -> None:
        """Delete a calendar resource via HTTP DELETE.

        RFC Reference:
            - RFC 4918 Section 9.7: DELETE Method.

        Args:
            url: Target resource URI path.
            etag: Optional ETag for conditional If-Match check.

        Raises:
            CalDavAuthError: If authentication is required or rejected (HTTP 401/403).
            aiohttp.ClientResponseError: If the deletion fails.
        """
        session = await self._get_session()
        self._warn_insecure_auth(url)
        headers = {}
        if etag:
            headers["If-Match"] = f'"{etag}"' if not etag.startswith('"') else etag

        async with session.delete(url, headers=headers) as resp:
            self._check_response(resp)

    async def calendar_query(
        self,
        url: str,
        component: str = "VEVENT",
        time_start: str | None = None,
        time_end: str | None = None,
    ) -> list[ReportResource]:
        """Perform a CalDAV calendar-query REPORT to filter resources by type and time range.

        Sends a REPORT request with a <C:calendar-query> body that filters
        calendar resources by component type (VEVENT, VTODO, etc.) and optional
        time-range constraints. Returns matching resources with ETags and iCalendar data.

        RFC Reference:
            - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.
            - RFC 3253 Section 3.6: REPORT Method.

        Args:
            url: Target collection URI path.
            component: iCalendar component type to filter (default 'VEVENT').
            time_start: Optional UTC start boundary (e.g. '20260701T000000Z').
            time_end: Optional UTC end boundary (e.g. '20260801T000000Z').

        Returns:
            List of ReportResource objects for matching calendar resources.

        Raises:
            CalDavAuthError: If authentication is required or rejected (HTTP 401/403).
            aiohttp.ClientResponseError: If the server returns a non-207 status code.
        """
        session = await self._get_session()
        self._warn_insecure_auth(url)
        body = build_calendar_query_xml(
            component=component, time_start=time_start, time_end=time_end
        )
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Depth": "1",
        }

        async with session.request("REPORT", url, data=body, headers=headers) as resp:
            self._check_response(resp)
            content = await resp.read()
            return parse_report_response(content)

    async def calendar_multiget(
        self,
        url: str,
        hrefs: list[str],
    ) -> list[ReportResource]:
        """Perform a CalDAV calendar-multiget REPORT to batch-fetch resources by href.

        Sends a REPORT request with a <C:calendar-multiget> body containing
        a list of resource hrefs. Returns the resources with ETags and iCalendar
        data in a single round-trip, avoiding individual GET requests.

        RFC Reference:
            - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.
            - RFC 3253 Section 3.6: REPORT Method.

        Args:
            url: Target collection URI path.
            hrefs: List of resource href paths to retrieve.

        Returns:
            List of ReportResource objects for found resources.

        Raises:
            CalDavAuthError: If authentication is required or rejected (HTTP 401/403).
            aiohttp.ClientResponseError: If the server returns a non-207 status code.
        """
        session = await self._get_session()
        self._warn_insecure_auth(url)
        body = build_calendar_multiget_xml(hrefs=hrefs)
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
        }

        async with session.request("REPORT", url, data=body, headers=headers) as resp:
            self._check_response(resp)
            content = await resp.read()
            return parse_report_response(content)

    async def principal_property_search(
        self,
        url: str = "/",
        match: str = "",
        prop_tag: str = "displayname",
    ) -> list[PropfindItem]:
        """Perform a WebDAV principal-property-search REPORT (RFC 3744 §9.4).

        Search for principal resources (users, groups, or services) matching property criteria.

        Use Cases for Clients:
            - **User Auto-completion & Invitee Search**: In CalDAV scheduling applications,
              when a user types a name or email in an event invitation field (e.g. "Bernard"),
              the client uses this REPORT to search for matching user principals on the server
              and retrieve their principal paths and calendar user addresses (`mailto:`).
            - **Directory Lookup**: Discovering other users or resource principals available on a
              shared CalDAV server.

        RFC Reference:
            - RFC 3744 Section 9.4: DAV:principal-property-search REPORT.

        Args:
            url: Target principal collection URI path (default '/').
            match: Case-insensitive search string to match against principal properties.
            prop_tag: Local property tag name to search (default 'displayname').

        Returns:
            List of parsed PropfindItem objects representing matching principals.
        """
        session = await self._get_session()
        self._warn_insecure_auth(url)
        body = build_principal_property_search_xml(match=match, prop_tag=prop_tag)
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Depth": "0",
        }

        async with session.request("REPORT", url, data=body, headers=headers) as resp:
            self._check_response(resp)
            content = await resp.read()
            return parse_multistatus_xml(content)

    async def _sync_collection_page(
        self,
        url: str,
        sync_token: str | None = "",
        limit: int | None = None,
    ) -> tuple[list[ReportResource], str | None]:
        """Fetch a single page of sync-collection REPORT results."""
        session = await self._get_session()
        self._warn_insecure_auth(url)
        body = build_sync_collection_xml(sync_token=sync_token or "", limit=limit)
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Depth": "1",
        }

        async with session.request("REPORT", url, data=body, headers=headers) as resp:
            self._check_response(resp)
            content = await resp.read()
            return parse_sync_collection_response(content)

    async def sync_collection(
        self,
        url: str,
        sync_token: str | None = "",
        limit: int | None = None,
        auto_paginate: bool = False,
    ) -> tuple[list[ReportResource], str | None]:
        """Perform a WebDAV sync-collection REPORT (RFC 6578).

        Fetch updated calendar resources changed since the specified sync token.

        Use Cases for Clients:
            - **Fast Synchronization**: Allows CalDAV client applications (e.g. mobile/desktop apps)
              to synchronize only resources that have been added, modified, or deleted since the
              last sync, drastically reducing bandwidth and latency compared to full collection scans.
            - **Multi-page Auto-pagination**: When auto_paginate is True, iteratively requests
              intermediate sync token pages until all pages are retrieved and the final sync token
              is reached (RFC 6578 §3.7).

        RFC Reference:
            - RFC 6578 Section 3 & 3.7: WebDAV Sync Protocol & DAV:limit.

        Args:
            url: Target calendar collection URI path.
            sync_token: Prior sync token string, or empty string for initial sync.
            limit: Optional result limit integer for paginated sync queries.
            auto_paginate: If True, automatically iterate through intermediate sync tokens.

        Returns:
            Tuple of (list of ReportResource items for updated resources, server sync_token string or None).
        """
        if not auto_paginate:
            return await self._sync_collection_page(url, sync_token, limit)

        all_resources: list[ReportResource] = []
        current_token: str = sync_token or ""
        seen_tokens: set[str] = set()

        while True:
            page_resources, next_token = await self._sync_collection_page(
                url, current_token, limit
            )
            all_resources.extend(page_resources)

            if next_token is None:
                return all_resources, current_token
            if next_token == current_token or next_token in seen_tokens:
                return all_resources, next_token

            seen_tokens.add(current_token)
            current_token = next_token
