"""HTTP Client Transport for WebDAV and CalDAV operations.

RFC References:
  - RFC 4918 Section 9.1: PROPFIND Method.
  - RFC 4918 Section 9.7: DELETE Method.
  - RFC 4791 Section 5.2: Calendar Object Resources (GET / PUT).
"""

import aiohttp

from icaldav.xml.propfind import PropfindItem, build_propfind_xml, parse_multistatus_xml


class CalDavClient:
    """Asynchronous client for interacting with WebDAV / CalDAV servers using aiohttp.

    RFC References:
        - RFC 4918: WebDAV Core Protocols.
        - RFC 4791: CalDAV Extensions.
    """

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        """Initialize CalDavClient.

        Args:
            session: Optional existing aiohttp.ClientSession. If None, an internal session is created.
        """
        self._session = session
        self._owned_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Retrieve active ClientSession, instantiating one if needed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owned_session = True
        return self._session

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
            aiohttp.ClientResponseError: If the server returns a non-207 status code.
        """
        session = await self._get_session()
        body = build_propfind_xml(props or ["resourcetype", "getetag", "displayname"])
        headers = {
            "Depth": str(depth),
            "Content-Type": "application/xml; charset=utf-8",
        }

        async with session.request("PROPFIND", url, data=body, headers=headers) as resp:
            resp.raise_for_status()
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
            aiohttp.ClientResponseError: If the HTTP response status is not 200 OK.
        """
        session = await self._get_session()
        headers = {"Accept": "text/calendar, text/plain, */*"}

        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
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
            aiohttp.ClientResponseError: If the server rejects the request.
        """
        session = await self._get_session()
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            headers["If-Match"] = f'"{etag}"' if not etag.startswith('"') else etag

        async with session.put(
            url, data=ics_content.encode("utf-8"), headers=headers
        ) as resp:
            resp.raise_for_status()
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
            aiohttp.ClientResponseError: If the deletion fails.
        """
        session = await self._get_session()
        headers = {}
        if etag:
            headers["If-Match"] = f'"{etag}"' if not etag.startswith('"') else etag

        async with session.delete(url, headers=headers) as resp:
            resp.raise_for_status()
