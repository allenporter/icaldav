"""Server discovery handlers for OPTIONS and /.well-known/caldav.

RFC Reference:
    - RFC 4918 Section 9.10: OPTIONS Method.
    - RFC 4791 Section 5.1: CalDAV OPTIONS Response.
    - RFC 6764 Section 5: CalDAV Well-Known Service Discovery.
"""

from aiohttp import web


async def handle_options(request: web.Request) -> web.Response:
    """Handle OPTIONS request advertising WebDAV and CalDAV capabilities."""
    headers = {
        "Allow": "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, REPORT, MKCALENDAR",
        "DAV": "1, calendar-access",
    }
    return web.Response(status=200, headers=headers)


async def handle_well_known(request: web.Request) -> web.Response:
    """Handle /.well-known/caldav discovery redirect."""
    raise web.HTTPMovedPermanently(location="/")
