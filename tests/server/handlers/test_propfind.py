"""Unit tests for server PROPFIND handlers."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_root_propfind_autodiscovery() -> None:
    """Test PROPFIND / root autodiscovery endpoint."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        resp = await client.request("PROPFIND", "/")
        assert resp.status == 207
        xml_text = await resp.text()
        assert "current-user-principal" in xml_text
        assert "calendar-home-set" in xml_text


@pytest.mark.asyncio
async def test_propfind_collection_depths() -> None:
    """Test PROPFIND on collection with Depth 0 vs Depth 1."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        # Depth 0 returns collection node only
        resp_d0 = await client.request("PROPFIND", "/work", headers={"Depth": "0"})
        assert resp_d0.status == 207

        # Depth 1 returns collection and items
        resp_d1 = await client.request("PROPFIND", "/work", headers={"Depth": "1"})
        assert resp_d1.status == 207


@pytest.mark.asyncio
async def test_propfind_individual_resource() -> None:
    """Test PROPFIND query on an individual calendar object resource."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        # Non-existent resource returns 404
        pf_resp = await client.request("PROPFIND", "/work/missing.ics")
        assert pf_resp.status == 404

        # Upload resource
        ics_payload = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:999\r\nEND:VEVENT\r\nEND:VCALENDAR"
        )
        await client.put("/work/event999.ics", data=ics_payload)

        # PROPFIND existing resource returns 207 Multi-Status XML
        pf_resp = await client.request("PROPFIND", "/work/event999.ics")
        assert pf_resp.status == 207
        xml_text = await pf_resp.text()
        assert "/work/event999.ics" in xml_text
        assert "getetag" in xml_text


@pytest.mark.asyncio
async def test_propfind_404_propstat_grouping() -> None:
    """Test PROPFIND with requested <d:prop> grouping 200 OK and 404 Not Found propstats."""
    store = MemoryStore()
    app = create_app(store)
    propfind_xml = b"""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
    <d:prop>
        <d:resourcetype/>
        <d:unsupported_custom_property/>
    </d:prop>
</d:propfind>"""

    async with TestClient(TestServer(app)) as client:
        resp = await client.request("PROPFIND", "/work", data=propfind_xml)
        assert resp.status == 207
        xml_text = await resp.text()
        assert "HTTP/1.1 200 OK" in xml_text
        assert "HTTP/1.1 404 Not Found" in xml_text
        assert "unsupported_custom_property" in xml_text
