"""Unit tests for CalDavClient public interface."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.client.client import CalDavClient
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
