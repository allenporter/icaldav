"""Unit tests for server REPORT handlers."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_report_error_paths() -> None:
    """Test router error responses for invalid REPORT requests."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        # Empty body REPORT returns 400
        resp = await client.request("REPORT", "/work", data="")
        assert resp.status == 400

        # Invalid XML REPORT returns 400
        resp = await client.request("REPORT", "/work", data="<not-valid-xml")
        assert resp.status == 400

        # Unsupported REPORT type tag returns 400
        resp = await client.request(
            "REPORT", "/work", data="<unsupported-report xmlns='DAV:'/>"
        )
        assert resp.status == 400
