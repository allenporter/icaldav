"""Unit tests for server collection handlers (MKCALENDAR)."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_mkcalendar_create_collection() -> None:
    """Test MKCALENDAR handler creates a collection."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with TestClient(server) as client:
        resp = await client.request("MKCALENDAR", "/newcal")
        assert resp.status == 201
        assert await store.collection_exists("newcal") is True


@pytest.mark.asyncio
async def test_mkcalendar_duplicate_collection() -> None:
    """Test MKCALENDAR returns 405 when collection already exists."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with TestClient(server) as client:
        resp = await client.request("MKCALENDAR", "/work")
        assert resp.status == 201
        resp_dup = await client.request("MKCALENDAR", "/work")
        assert resp_dup.status == 405


@pytest.mark.asyncio
async def test_collection_proppatch() -> None:
    """Test PROPPATCH on calendar collections."""
    store = MemoryStore()
    app = create_app(store)

    async with (
        TestServer(app) as server,
        TestClient(server) as client,
    ):
        # PROPPATCH on non-existent collection returns 404
        patch_body = (
            '<?xml version="1.0"?>'
            '<D:propertyupdate xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:set><D:prop><D:displayname>Work Team Calendar</D:displayname></D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp_404 = await client.request("PROPPATCH", "/work", data=patch_body)
        assert resp_404.status == 404

        # Create collection
        assert (await client.request("MKCALENDAR", "/work")).status == 201

        # PROPPATCH sets displayname
        resp_207 = await client.request("PROPPATCH", "/work", data=patch_body)
        assert resp_207.status == 207
        assert "200 OK" in await resp_207.text()

        # PROPFIND discovers new displayname
        propfind_resp = await client.request(
            "PROPFIND", "/work", headers={"Depth": "0"}
        )
        assert propfind_resp.status == 207
        assert "Work Team Calendar" in await propfind_resp.text()
