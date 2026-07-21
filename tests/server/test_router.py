"""Unit tests for CalDavRouter application creation and top-level router dispatch."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import CalDavRouter
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_router_create_app() -> None:
    """Test CalDavRouter instantiation and create_app factory."""
    store = MemoryStore()
    router = CalDavRouter(store)
    app = router.create_app()
    assert app is not None

    async with TestClient(TestServer(app)) as client:
        resp = await client.options("/work")
        assert resp.status == 200
        assert "PROPFIND" in resp.headers["Allow"]
        assert "calendar-access" in resp.headers["DAV"]
