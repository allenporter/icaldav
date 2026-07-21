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
