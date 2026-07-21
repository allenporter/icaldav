"""Unit tests for CalDavRouter endpoints using aiohttp.test_utils."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_options_endpoint() -> None:
    """Test OPTIONS endpoint capability headers."""
    store = MemoryStore()
    app = create_app(store)

    async with TestClient(TestServer(app)) as client:
        resp = await client.options("/work")
        assert resp.status == 200
        assert "PROPFIND" in resp.headers["Allow"]
        assert "calendar-access" in resp.headers["DAV"]


@pytest.mark.asyncio
async def test_server_crud_flow() -> None:
    """Test full HTTP CRUD flow against CalDavRouter."""
    store = MemoryStore()
    app = create_app(store)

    async with TestClient(TestServer(app)) as client:
        # GET non-existent resource returns 404
        get_resp = await client.get("/work/event1.ics")
        assert get_resp.status == 404

        # PUT resource
        ics_payload = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:123\r\nEND:VEVENT\r\nEND:VCALENDAR"
        )
        put_resp = await client.put("/work/event1.ics", data=ics_payload)
        assert put_resp.status == 201
        assert "ETag" in put_resp.headers
        etag = put_resp.headers["ETag"].strip('"')

        # GET resource returns 200 OK
        get_resp = await client.get("/work/event1.ics")
        assert get_resp.status == 200
        assert await get_resp.text() == ics_payload
        assert get_resp.headers["ETag"].strip('"') == etag

        # PROPFIND collection lists event1.ics
        pf_resp = await client.request("PROPFIND", "/work", headers={"Depth": "1"})
        assert pf_resp.status == 207
        xml_text = await pf_resp.text()
        assert "/work/event1.ics" in xml_text

        # DELETE resource
        del_resp = await client.delete("/work/event1.ics")
        assert del_resp.status == 204

        # GET after DELETE returns 404
        get_resp = await client.get("/work/event1.ics")
        assert get_resp.status == 404


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_root_propfind_autodiscovery() -> None:
    """Test PROPFIND / root autodiscovery endpoint."""
    store = MemoryStore()
    app = create_app(store)

    async with TestClient(TestServer(app)) as client:
        resp = await client.request("PROPFIND", "/")
        assert resp.status == 207
        xml_text = await resp.text()
        assert "<d:href>/</d:href>" in xml_text or "<href>/</href>" in xml_text
        assert "current-user-principal" in xml_text
        assert "calendar-home-set" in xml_text


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


@pytest.mark.asyncio
async def test_propfind_individual_resource() -> None:
    """Test PROPFIND query on an individual calendar object resource."""
    store = MemoryStore()
    app = create_app(store)

    async with TestClient(TestServer(app)) as client:
        # PROPFIND non-existent resource returns 404
        pf_resp = await client.request("PROPFIND", "/work/missing.ics")
        assert pf_resp.status == 404

        # PUT resource
        ics_payload = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:999\r\nEND:VEVENT\r\nEND:VCALENDAR"
        )
        await client.put("/work/event999.ics", data=ics_payload)

        # PROPFIND existing resource returns 207 Multi-Status XML with ETag
        pf_resp = await client.request("PROPFIND", "/work/event999.ics")
        assert pf_resp.status == 207
        xml_text = await pf_resp.text()
        assert "/work/event999.ics" in xml_text
        assert "getetag" in xml_text


@pytest.mark.asyncio
async def test_report_error_paths() -> None:
    """Test router error responses for invalid REPORT requests."""
    store = MemoryStore()
    app = create_app(store)

    async with TestClient(TestServer(app)) as client:
        # 1. Empty body REPORT returns 400
        resp = await client.request("REPORT", "/work", data="")
        assert resp.status == 400

        # 2. Invalid XML REPORT returns 400
        resp = await client.request("REPORT", "/work", data="<not-valid-xml")
        assert resp.status == 400

        # 3. Unsupported REPORT type tag returns 400
        resp = await client.request(
            "REPORT", "/work", data="<unsupported-report xmlns='DAV:'/>"
        )
        assert resp.status == 400
