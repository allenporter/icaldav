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

import aiohttp

from icaldav.client.auth import AuthProfile
from icaldav.client.exceptions import CalDavAuthError
from icaldav.client.oauth import OAuthTokenManager
from icaldav.xml.propfind.models import PropfindItem
from icaldav.xml.propfind.request import build_propfind_xml
from icaldav.xml.propfind.response import parse_multistatus_xml
from icaldav.xml.report.models import ReportResource
from icaldav.xml.report.request import (
    build_calendar_multiget_xml,
    build_calendar_query_xml,
)
from icaldav.xml.report.response import parse_report_response


def _resolve_credentials(
    username: str | None,
    password: str | None,
    token: str | None,
    auth: aiohttp.BasicAuth | None,
    auth_profile: AuthProfile | None,
) -> tuple[aiohttp.BasicAuth | None, str | None]:
    """Resolve basic auth object and bearer token from parameters or AuthProfile."""
    if auth or username or token:
        resolved_auth = auth or (
            aiohttp.BasicAuth(username, password) if username and password else None
        )
        return resolved_auth, token
    if auth_profile:
        if auth_profile.auth_type == "basic":
            return auth_profile.basic_auth, None
        if auth_profile.auth_type in ("oauth", "bearer"):
            return None, auth_profile.token
    return None, None


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
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        auth: aiohttp.BasicAuth | None = None,
        auth_profile: AuthProfile | None = None,
    ) -> None:
        """Initialize CalDavClient with optional session and credentials.

        Credentials can be provided either via explicit username/password/token
        parameters or via an AuthProfile with automatic OAuth token refresh support.

        Args:
            session: Optional existing aiohttp.ClientSession. If None, an internal session is created.
            username: Optional HTTP Basic Auth username string.
            password: Optional HTTP Basic Auth password string.
            token: Optional Bearer authentication token string.
            auth: Optional pre-configured aiohttp.BasicAuth object.
            auth_profile: Optional AuthProfile for credential management with
                OAuth auto-refresh support (RFC 6749 Section 6).
        """
        self._session = session
        self._owned_session = session is None
        self._auth_profile = auth_profile
        self.username = username or (auth_profile.username if auth_profile else None)
        self.password = password or (auth_profile.password if auth_profile else None)
        self.auth, self.token = _resolve_credentials(
            username, password, token, auth, auth_profile
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Retrieve active ClientSession, instantiating one with configured auth if needed.

        Ensures OAuth tokens are refreshed before creating or reusing sessions.
        """
        if self._auth_profile:
            fresh_token = await OAuthTokenManager(
                self._auth_profile
            ).ensure_fresh_token()
            if fresh_token and fresh_token != self.token:
                self.token = fresh_token
                if self._session is not None and not self._session.closed:
                    await self._session.close()
                self._session = None
        if self._session is None or self._session.closed:
            headers: dict[str, str] = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            self._session = aiohttp.ClientSession(
                auth=self.auth,
                headers=headers if headers else None,
            )
            self._owned_session = True
        return self._session

    def _warn_insecure_auth(self, url: str) -> None:
        """Emit a warning if credentials are being sent over non-HTTPS."""
        if (self.auth or self.token) and not url.startswith("https://"):
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

    async def __aenter__(self) -> "CalDavClient":
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
