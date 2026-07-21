"""Unit tests for CalDavClient public interface and authentication."""

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from icaldav.client.client import CalDavClient
from icaldav.client.exceptions import CalDavAuthError
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_client_context_manager() -> None:
    """Test CalDavClient lifecycle and operations using async context manager."""
    store = MemoryStore()
    app = create_app(store)

    async with TestServer(app) as server:
        async with TestClient(server) as test_client:
            async with CalDavClient(session=test_client.session) as client:
                url = str(server.make_url("/work"))
                items = await client.propfind(url, depth=0)
                assert len(items) == 1
                assert items[0].is_collection is True


@pytest.mark.asyncio
async def test_client_auth_error_challenge_parsing() -> None:
    """Test that 401 response with WWW-Authenticate header raises CalDavAuthError with parsed challenges."""

    async def handle_401(request: web.Request) -> web.Response:
        headers = {
            "WWW-Authenticate": 'Basic realm="TestRealm", Bearer realm="OAuthRealm"'
        }
        return web.Response(status=401, headers=headers)

    app = web.Application()
    app.router.add_route("PROPFIND", "/protected", handle_401)

    async with TestServer(app) as server:
        async with TestClient(server) as test_client:
            async with CalDavClient(session=test_client.session) as client:
                url = str(server.make_url("/protected"))
                with pytest.raises(CalDavAuthError) as exc_info:
                    await client.propfind(url)

                err = exc_info.value
                assert err.status == 401
                assert err.url == url
                assert len(err.challenges) > 0
                assert "Basic" in err.parse_schemes(err.challenges)
