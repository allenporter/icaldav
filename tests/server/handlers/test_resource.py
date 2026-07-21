"""Unit tests for server GET/PUT/DELETE resource handlers."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_resource_get_put_delete_flow() -> None:
    """Test full HTTP GET, PUT, and DELETE flow on calendar resources."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        # GET non-existent returns 404
        assert (await client.get("/work/event1.ics")).status == 404

        # DELETE non-existent returns 404
        assert (await client.delete("/work/event1.ics")).status == 404

        # PUT resource
        ics_payload = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:123\r\nEND:VEVENT\r\nEND:VCALENDAR"
        )
        put_resp = await client.put("/work/event1.ics", data=ics_payload)
        assert put_resp.status == 201

        # PUT update existing resource returns 204
        put_update = await client.put("/work/event1.ics", data=ics_payload)
        assert put_update.status == 204

        # GET returns 200 OK
        get_resp = await client.get("/work/event1.ics")
        assert get_resp.status == 200
        assert await get_resp.text() == ics_payload

        # DELETE returns 204
        del_resp = await client.delete("/work/event1.ics")
        assert del_resp.status == 204
