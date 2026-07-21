"""Unit tests for server discovery handlers."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_well_known_caldav_redirect() -> None:
    """/.well-known/caldav returns 301 redirect to /."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with TestClient(server) as client:
        resp = await client.get("/.well-known/caldav", allow_redirects=False)
        assert resp.status == 301
        assert resp.headers["Location"] == "/"
