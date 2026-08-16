"""Unit tests for authentication negotiation and server probing."""

from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from icaldav.client.negotiator import (
    KNOWN_OAUTH_ISSUERS,
    AuthNegotiator,
)


async def test_probe_no_auth_required() -> None:
    """Test that a 200 PROPFIND response is detected as no authentication required."""

    async def handle_propfind(request: web.Request) -> web.Response:
        return web.Response(status=200, text="OK")

    app = web.Application()
    app.router.add_route("PROPFIND", "/dav/", handle_propfind)

    async with TestServer(app) as server:
        url = str(server.make_url("/dav/"))
        negotiator = AuthNegotiator()
        methods = await negotiator.probe(url)

    assert len(methods) == 1
    assert methods[0].scheme == "none"


async def test_probe_basic_auth() -> None:
    """Test that 401 response with Basic WWW-Authenticate returns basic AuthMethod."""

    async def handle_propfind(request: web.Request) -> web.Response:
        return web.Response(
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="TestRealm"'},
        )

    app = web.Application()
    app.router.add_route("PROPFIND", "/dav/", handle_propfind)

    async with TestServer(app) as server:
        url = str(server.make_url("/dav/"))
        negotiator = AuthNegotiator()
        methods = await negotiator.probe(url)

    assert len(methods) == 1
    assert methods[0].scheme == "basic"
    assert methods[0].realm == "TestRealm"


async def test_probe_bearer_known_provider() -> None:
    """Test Bearer challenge with known OAuth provider triggers OpenID discovery."""

    async def handle_discovery(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            }
        )

    discovery_app = web.Application()
    discovery_app.router.add_get("/.well-known/openid-configuration", handle_discovery)

    async def handle_propfind(request: web.Request) -> web.Response:
        return web.Response(
            status=401,
            headers={"WWW-Authenticate": 'Bearer realm="Google"'},
        )

    caldav_app = web.Application()
    caldav_app.router.add_route("PROPFIND", "/dav/", handle_propfind)

    async with TestServer(discovery_app) as discovery_server:
        discovery_url = str(discovery_server.make_url(""))

        async with TestServer(caldav_app) as caldav_server:
            caldav_url = str(caldav_server.make_url("/dav/"))
            caldav_host = caldav_server.host

            # Patch KNOWN_OAUTH_ISSUERS to map the test CalDAV hostname to the
            # test discovery server URL.
            with patch.dict(KNOWN_OAUTH_ISSUERS, {caldav_host: discovery_url}):
                negotiator = AuthNegotiator()
                methods = await negotiator.probe(caldav_url)

    assert len(methods) == 1
    assert methods[0].scheme == "oauth"
    assert methods[0].realm == "Google"
    assert methods[0].oauth_config is not None
    assert methods[0].oauth_config.auth_uri == "https://auth.example.com/authorize"
    assert methods[0].oauth_config.token_uri == "https://auth.example.com/token"


async def test_probe_bearer_unknown_provider() -> None:
    """Test Bearer challenge with unknown hostname and no discovery falls back to 'bearer'."""

    async def handle_propfind(request: web.Request) -> web.Response:
        return web.Response(
            status=401,
            headers={"WWW-Authenticate": 'Bearer realm="Unknown"'},
        )

    # Discovery will fail because the server doesn't serve /.well-known/
    async def handle_not_found(request: web.Request) -> web.Response:
        return web.Response(status=404)

    app = web.Application()
    app.router.add_route("PROPFIND", "/dav/", handle_propfind)
    app.router.add_get("/.well-known/openid-configuration", handle_not_found)

    async with TestServer(app) as server:
        url = str(server.make_url("/dav/"))
        negotiator = AuthNegotiator()
        methods = await negotiator.probe(url)

    assert len(methods) == 1
    assert methods[0].scheme == "bearer"
    assert methods[0].realm == "Unknown"
    assert methods[0].oauth_config is None


async def test_probe_multiple_challenges() -> None:
    """Test 401 with multiple WWW-Authenticate challenges returns all methods."""

    async def handle_propfind(request: web.Request) -> web.Response:
        return web.Response(
            status=401,
            headers={
                "WWW-Authenticate": 'Basic realm="Test", Bearer realm="OAuth"',
            },
        )

    app = web.Application()
    app.router.add_route("PROPFIND", "/dav/", handle_propfind)

    async with TestServer(app) as server:
        url = str(server.make_url("/dav/"))
        negotiator = AuthNegotiator()
        methods = await negotiator.probe(url)

    assert len(methods) == 2
    schemes = [m.scheme for m in methods]
    assert "basic" in schemes
    # Bearer resolves to either 'oauth' or 'bearer' depending on discovery;
    # with an unknown test host and no discovery endpoint it falls back.
    assert "bearer" in schemes or "oauth" in schemes


async def test_probe_no_www_authenticate() -> None:
    """Test 401 with no WWW-Authenticate header returns scheme='unknown'."""

    async def handle_propfind(request: web.Request) -> web.Response:
        return web.Response(status=401)

    app = web.Application()
    app.router.add_route("PROPFIND", "/dav/", handle_propfind)

    async with TestServer(app) as server:
        url = str(server.make_url("/dav/"))
        negotiator = AuthNegotiator()
        methods = await negotiator.probe(url)

    assert len(methods) == 1
    assert methods[0].scheme == "unknown"


def test_known_oauth_issuers_mapping() -> None:
    """Test that KNOWN_OAUTH_ISSUERS contains expected provider entries."""
    # Google
    assert "apidata.googleusercontent.com" in KNOWN_OAUTH_ISSUERS
    assert "www.googleapis.com" in KNOWN_OAUTH_ISSUERS
    assert (
        KNOWN_OAUTH_ISSUERS["apidata.googleusercontent.com"]
        == "https://accounts.google.com"
    )
    assert KNOWN_OAUTH_ISSUERS["www.googleapis.com"] == "https://accounts.google.com"

    # Microsoft
    assert "outlook.office365.com" in KNOWN_OAUTH_ISSUERS
    assert (
        KNOWN_OAUTH_ISSUERS["outlook.office365.com"]
        == "https://login.microsoftonline.com/common/v2.0"
    )

    # iCloud (Basic auth only — empty issuer string)
    assert "caldav.icloud.com" in KNOWN_OAUTH_ISSUERS
    assert KNOWN_OAUTH_ISSUERS["caldav.icloud.com"] == ""

    # Fastmail (Basic auth only — empty issuer string)
    assert "caldav.fastmail.com" in KNOWN_OAUTH_ISSUERS
    assert KNOWN_OAUTH_ISSUERS["caldav.fastmail.com"] == ""


async def test_probe_bearer_missing_header_known_provider() -> None:
    """Test 401 response missing WWW-Authenticate header still resolves OAuth for known host."""

    async def handle_discovery(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            }
        )

    discovery_app = web.Application()
    discovery_app.router.add_get("/.well-known/openid-configuration", handle_discovery)

    async def handle_propfind(request: web.Request) -> web.Response:
        # 401 response without WWW-Authenticate header (like Google CalDAV)
        return web.Response(status=401)

    caldav_app = web.Application()
    caldav_app.router.add_route("PROPFIND", "/dav/", handle_propfind)

    async with TestServer(discovery_app) as discovery_server:
        discovery_url = str(discovery_server.make_url(""))

        async with TestServer(caldav_app) as caldav_server:
            caldav_url = str(caldav_server.make_url("/dav/"))
            caldav_host = caldav_server.host

            with patch.dict(KNOWN_OAUTH_ISSUERS, {caldav_host: discovery_url}):
                negotiator = AuthNegotiator()
                methods = await negotiator.probe(caldav_url)

    assert len(methods) == 1
    assert methods[0].scheme == "oauth"
    assert methods[0].oauth_config is not None
    assert methods[0].oauth_config.auth_uri == "https://auth.example.com/authorize"
